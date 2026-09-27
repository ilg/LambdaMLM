"""Find LambdaMLM deployments in an AWS account.

    scripts/find-deployments --profile PROFILE [--region REGION ...]

Searches every region (or the ones given) for:
- LambdaMLM stacks (tagged lambdamlm=true), with their bucket, receipt rule and
  last update; `scripts/pull-config` turns one into a samconfig.toml
  environment; and
- older, fabfile-era deployments: Lambda functions, not part of a stack, whose
  code is LambdaMLM's, with the SES receipt rules that invoke them.
"""

import argparse
import io
import urllib.request
import zipfile

from deploytools.common import AWS, STACK_TAG, main_wrapper, stack_parameters


def regions(profile):
    result = AWS(profile, 'us-east-1').json('ec2', 'describe-regions')
    return sorted(r['RegionName'] for r in result['Regions'])


def stacks(aws):
    found = []
    for stack in aws.json('cloudformation', 'describe-stacks').get('Stacks', []):
        tags = {t['Key']: t['Value'] for t in stack.get('Tags', [])}
        if tags.get(STACK_TAG[0]) == STACK_TAG[1]:
            found.append(stack)
    return found


def legacy_functions(aws):
    functions = []
    marker = None
    while True:
        args = ['lambda', 'list-functions'] + (['--marker', marker] if marker else [])
        page = aws.json(*args)
        functions += page.get('Functions', [])
        marker = page.get('NextMarker')
        if not marker:
            break
    found = []
    for f in functions:
        if f.get('Handler') != 'lambda.lambda_handler':
            continue
        tags = aws.json('lambda', 'list-tags', '--resource', f['FunctionArn'], check=False) or {}
        if 'aws:cloudformation:stack-name' in tags.get('Tags', {}):
            continue
        if is_lambdamlm(aws, f['FunctionName']):
            found.append(f)
    return found


def is_lambdamlm(aws, function):
    """Whether a function's code package is LambdaMLM's (other projects share the handler name)."""
    location = aws.json('lambda', 'get-function', '--function-name', function)['Code']['Location']
    with urllib.request.urlopen(location) as response:
        names = zipfile.ZipFile(io.BytesIO(response.read())).namelist()
    return 'listobj.py' in names and 'lambda.py' in names


def _bucket(rule):
    return next((a['S3Action']['BucketName'] for a in rule.get('Actions', []) if 'S3Action' in a), None)


def _covers(earlier, rule):
    """Whether an earlier rule receives (at least) the mail the rule receives."""
    return not earlier.get('Recipients') or set(rule.get('Recipients') or ()) <= set(earlier['Recipients'])


def rules_invoking(aws, function_arn):
    """(rule set, rule, enabled, recipients, bucket) for each active rule invoking the function.

    The bucket is the rule's own S3 action's, or else that of an earlier rule
    covering the same mail (the fabfile-era setup used a separate rule to
    store it).
    """
    active = aws.json('ses', 'describe-active-receipt-rule-set', check=False) or {}
    all_rules = active.get('Rules', [])
    rules = []
    for index, rule in enumerate(all_rules):
        for action in rule.get('Actions', []):
            if (action.get('LambdaAction') or {}).get('FunctionArn') == function_arn:
                bucket = _bucket(rule) or next(
                        (_bucket(r) for r in reversed(all_rules[:index]) if _bucket(r) and _covers(r, rule)), None)
                rules.append((active['Metadata']['Name'], rule['Name'], rule.get('Enabled'),
                              rule.get('Recipients') or ['(all verified domains)'], bucket))
    return rules


def main(args):
    parser = argparse.ArgumentParser(prog='scripts/find-deployments', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--profile')
    parser.add_argument('--region', action='append')
    options = parser.parse_args(args)
    found = 0
    for region in options.region or regions(options.profile):
        aws = AWS(options.profile, region)
        for stack in stacks(aws):
            found += 1
            params = stack_parameters(stack)
            print('{}: stack {} ({}, updated {})'.format(
                    region, stack['StackName'], stack['StackStatus'],
                    stack.get('LastUpdatedTime', stack['CreationTime'])[:19]))
            print('    bucket {}; receipt rule set {!r} ({}); recipients {}'.format(
                    params.get('BucketName'), params.get('ReceiptRuleSetName'),
                    'enabled' if params.get('ReceiptRuleEnabled') == 'true' else 'disabled',
                    params.get('ReceiptRuleRecipients') or '(all verified domains)'))
            print('    scripts/pull-config --env NAME --profile {} --region {} --stack {}'.format(
                    options.profile or 'default', region, stack['StackName']))
        for function in legacy_functions(aws):
            found += 1
            print('{}: fabfile-era function {} ({}, code from {})'.format(
                    region, function['FunctionName'], function.get('Runtime'), function['LastModified'][:10]))
            for rule_set, rule, enabled, recipients, bucket in rules_invoking(aws, function['FunctionArn']):
                print('    invoked by rule {!r} in {!r} ({}) for {}; bucket {}'.format(
                        rule, rule_set, 'enabled' if enabled else 'disabled', ', '.join(recipients), bucket))
    if not found:
        print('No LambdaMLM deployments found.')


if __name__ == '__main__':
    main_wrapper(main)
