"""SES test inboxes: addresses whose mail is kept in an S3 bucket for the tests.

    scripts/e2e inbox setup <env> [--apply]
    scripts/e2e inbox teardown <env> [--apply]
    scripts/e2e inbox list <env> [<address>]

Setup and teardown only print what they would do unless given --apply.

Each inbox address gets its own receipt rule, at the start of the active rule
set, that stores its mail under inbox/<address>/ in the test bucket and then
stops, so no later rule (such as LambdaMLM's) sees it.  Separate rules keep
track of which address a message was delivered to, which headers alone don't
show (for Bcc'd mail, say).
"""

import json
import sys
import time

from botocore.exceptions import ClientError

from e2e.environment import RULE_PREFIX, TAG_KEY


def rule_name(env, address):
    return RULE_PREFIX + str(env.inboxes.index(address) + 1)


def planned_rules(env):
    rules = []
    for address in env.inboxes:
        rules.append({
            'Name': rule_name(env, address),
            'Enabled': True,
            'TlsPolicy': 'Optional',
            'ScanEnabled': True,
            'Recipients': [address],
            'Actions': [
                {'S3Action': {'BucketName': env.inbox_bucket,
                              'ObjectKeyPrefix': env.inbox_prefix(address)}},
                {'StopAction': {'Scope': 'RuleSet'}},
            ],
        })
    return rules


def bucket_policy(env):
    return json.dumps({
        'Version': '2012-10-17',
        'Statement': [{
            'Sid': 'AllowSESToStoreTestInboxMail',
            'Effect': 'Allow',
            'Principal': {'Service': 'ses.amazonaws.com'},
            'Action': 's3:PutObject',
            'Resource': 'arn:aws:s3:::{}/inbox/*'.format(env.inbox_bucket),
            'Condition': {'StringEquals': {'AWS:SourceAccount': env.account}},
        }],
    })


def existing_rules(env):
    ses = env.client('ses')
    rules = ses.describe_receipt_rule_set(RuleSetName=env.rule_set)['Rules']
    return [r['Name'] for r in rules]


def setup(env, apply):
    s3 = env.client('s3')
    ses = env.client('ses')
    active = ses.describe_active_receipt_rule_set().get('Metadata', {}).get('Name')
    if active != env.rule_set:
        sys.exit('The active rule set is {!r}, not {!r}; test inboxes only work in the active one.'
                 .format(active, env.rule_set))
    for address in env.inboxes:
        domain = address.split('@', 1)[1]
        status = ses.get_identity_verification_attributes(Identities=[domain])['VerificationAttributes']
        if status.get(domain, {}).get('VerificationStatus') != 'Success':
            sys.exit('{} is not a verified SES identity in {}.'.format(domain, env.region))

    steps = []
    try:
        s3.head_bucket(Bucket=env.inbox_bucket)
        print('Bucket {} already exists.'.format(env.inbox_bucket))
    except ClientError:
        steps.append(('Create bucket {} (tagged {}, public access blocked, 7-day expiry)'
                      .format(env.inbox_bucket, TAG_KEY), lambda: create_bucket(env)))
    steps.append(('Set bucket policy allowing SES to store under inbox/', lambda: s3.put_bucket_policy(
            Bucket=env.inbox_bucket, Policy=bucket_policy(env))))
    current = existing_rules(env)
    for rule in reversed(planned_rules(env)):
        if rule['Name'] in current:
            steps.append(('Update rule {} for {}'.format(rule['Name'], rule['Recipients'][0]),
                          lambda rule=rule: ses.update_receipt_rule(RuleSetName=env.rule_set, Rule=rule)))
        else:
            # Without After, SES puts a new rule at the start of the rule set.
            steps.append(('Add rule {} at the start of {}: {} -> s3://{}/{}, then stop'.format(
                              rule['Name'], env.rule_set, rule['Recipients'][0], env.inbox_bucket,
                              rule['Actions'][0]['S3Action']['ObjectKeyPrefix']),
                          lambda rule=rule: ses.create_receipt_rule(RuleSetName=env.rule_set, Rule=rule)))
    run_steps(steps, apply)


def create_bucket(env):
    s3 = env.client('s3')
    kwargs = {'Bucket': env.inbox_bucket}
    if env.region != 'us-east-1':
        kwargs['CreateBucketConfiguration'] = {'LocationConstraint': env.region}
    s3.create_bucket(**kwargs)
    s3.put_bucket_tagging(Bucket=env.inbox_bucket,
                          Tagging={'TagSet': [{'Key': TAG_KEY, 'Value': 'true'}]})
    s3.put_public_access_block(Bucket=env.inbox_bucket, PublicAccessBlockConfiguration={
        'BlockPublicAcls': True, 'IgnorePublicAcls': True,
        'BlockPublicPolicy': True, 'RestrictPublicBuckets': True})
    s3.put_bucket_lifecycle_configuration(Bucket=env.inbox_bucket, LifecycleConfiguration={
        'Rules': [{'ID': 'expire', 'Status': 'Enabled', 'Filter': {'Prefix': ''},
                   'Expiration': {'Days': 7}}]})


def teardown(env, apply):
    s3 = env.client('s3')
    ses = env.client('ses')
    steps = []
    for name in existing_rules(env):
        if name.startswith(RULE_PREFIX):
            steps.append(('Delete rule {} from {}'.format(name, env.rule_set),
                          lambda name=name: ses.delete_receipt_rule(RuleSetName=env.rule_set, RuleName=name)))
    try:
        tags = s3.get_bucket_tagging(Bucket=env.inbox_bucket)['TagSet']
    except ClientError:
        tags = None
    if tags is not None:
        if {'Key': TAG_KEY, 'Value': 'true'} not in tags:
            sys.exit("Bucket {} isn't tagged {}, so it wasn't created by the tests; leaving it."
                     .format(env.inbox_bucket, TAG_KEY))
        steps.append(('Empty and delete bucket {}'.format(env.inbox_bucket), lambda: delete_bucket(env)))
    run_steps(steps, apply)


def delete_bucket(env):
    s3 = env.client('s3')
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=env.inbox_bucket):
        keys = [{'Key': o['Key']} for o in page.get('Contents', [])]
        if keys:
            s3.delete_objects(Bucket=env.inbox_bucket, Delete={'Objects': keys})
    s3.delete_bucket(Bucket=env.inbox_bucket)


def run_steps(steps, apply):
    if not steps:
        print('Nothing to do.')
        return
    for description, action in steps:
        print(('' if apply else 'Would: ') + description)
        if apply:
            action()
    if not apply:
        print('(Nothing changed.  Run again with --apply to do this.)')


# ---------------------------------------------------------------- reading

def messages(env, address, since=None):
    """(key, last-modified, raw bytes) for each message stored for an inbox."""
    s3 = env.client('s3')
    found = []
    for page in s3.get_paginator('list_objects_v2').paginate(
            Bucket=env.inbox_bucket, Prefix=env.inbox_prefix(address)):
        for obj in page.get('Contents', []):
            if obj['Key'].endswith('AMAZON_SES_SETUP_NOTIFICATION'):
                continue
            if since is None or obj['LastModified'].timestamp() >= since:
                body = s3.get_object(Bucket=env.inbox_bucket, Key=obj['Key'])['Body'].read()
                found.append((obj['Key'], obj['LastModified'], body))
    return sorted(found, key=lambda m: m[1])


def wait_for(env, address, predicate, since, timeout=300, interval=10):
    deadline = time.time() + timeout
    while True:
        found = [m for m in messages(env, address, since) if predicate(m[2])]
        if found or time.time() >= deadline:
            return found
        time.sleep(interval)


def main(args):
    from e2e import environment
    if len(args) < 2 or args[0] not in ('setup', 'teardown', 'list'):
        sys.exit(__doc__)
    env = environment.load(args[1])
    apply = '--apply' in args
    if args[0] == 'setup':
        setup(env, apply)
    elif args[0] == 'teardown':
        teardown(env, apply)
    else:
        addresses = [a for a in args[2:] if not a.startswith('--')] or env.inboxes
        for address in addresses:
            for key, modified, body in messages(env, address):
                print('{}  {}  {} bytes'.format(modified.isoformat(), key, len(body)))
