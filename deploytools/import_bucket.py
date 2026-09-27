"""Adopt an existing deployment's S3 bucket into a new LambdaMLM stack.

    scripts/import-bucket --env NAME [--yes]

Run this once, before the first scripts/deploy, when moving a deployment made
with the old fabfile to a SAM stack.  It creates the environment's stack
containing only the bucket named by the environment's BucketName, and the
bucket's policy if it has one, without changing either or anything in the
bucket.  (CloudFormation won't create a bucket policy on a bucket that already
has one, so an existing policy is imported and then updated in place.)
scripts/deploy then adds the rest of the stack and applies the template's
bucket settings.  If the stack already holds the bucket (after a deploy that
was rolled back, say), only what's missing is imported.

CloudFormation can't create other resources in the same operation as an
import, which is why this is a separate step.  New deployments don't need it:
scripts/deploy creates the bucket.
"""

import argparse
import json
import os
import sys
import tempfile

from deploytools.common import Error, aws_for, describe_stack, load_environment, main_wrapper

CHANGE_SET_NAME = 'import-bucket'


def import_template(bucket, policy=None):
    """A template holding only the bucket (and its existing policy), with the full template's logical IDs.

    Both are Retain: besides being required for an import, that keeps the
    first deploy's replacement of the imported policy from deleting the policy
    it has just written (a bucket has only one).
    """
    resources = {
        'MailBucket': {
            'Type': 'AWS::S3::Bucket',
            'DeletionPolicy': 'Retain',
            'UpdateReplacePolicy': 'Retain',
            'Properties': {'BucketName': bucket},
        },
    }
    if policy is not None:
        resources['MailBucketPolicy'] = {
            'Type': 'AWS::S3::BucketPolicy',
            'DeletionPolicy': 'Retain',
            'Properties': {'Bucket': bucket, 'PolicyDocument': policy},
        }
    return json.dumps({
        'AWSTemplateFormatVersion': '2010-09-09',
        'Description': 'LambdaMLM: importing the existing bucket.  scripts/deploy adds the rest.',
        'Resources': resources,
    }, indent=2)


def resources_to_import(bucket, policy, already):
    resources = []
    if 'MailBucket' not in already:
        resources.append({'ResourceType': 'AWS::S3::Bucket', 'LogicalResourceId': 'MailBucket',
                          'ResourceIdentifier': {'BucketName': bucket}})
    if policy is not None and 'MailBucketPolicy' not in already:
        resources.append({'ResourceType': 'AWS::S3::BucketPolicy', 'LogicalResourceId': 'MailBucketPolicy',
                          'ResourceIdentifier': {'Bucket': bucket}})
    return resources


def main(args):
    parser = argparse.ArgumentParser(prog='scripts/import-bucket', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--env', required=True)
    parser.add_argument('--yes', action='store_true')
    options = parser.parse_args(args)
    env = load_environment(options.env)
    aws = aws_for(env)
    bucket = env.parameters.get('BucketName')
    if not bucket:
        raise Error('Environment {!r} has no BucketName parameter.'.format(env.name))
    if not aws.succeeds('s3api', 'head-bucket', '--bucket', bucket):
        raise Error("Bucket {} doesn't exist (or isn't yours), so there is nothing to import.  "
                    'For a new deployment, just run scripts/deploy.'.format(bucket))
    policy_result = aws.json('s3api', 'get-bucket-policy', '--bucket', bucket, check=False)
    policy = json.loads(policy_result['Policy']) if policy_result else None

    stack = describe_stack(aws, env.stack_name)
    already = set()
    if stack is not None:
        described = aws.json('cloudformation', 'describe-stack-resources', '--stack-name', env.stack_name)
        already = {r['LogicalResourceId'] for r in described['StackResources']}
        if already - {'MailBucket', 'MailBucketPolicy'}:
            raise Error('Stack {} already has more than the bucket, so there is nothing to import.'.format(
                    env.stack_name))
    resources = resources_to_import(bucket, policy, already)
    if not resources:
        raise Error('Stack {} already holds the bucket and its policy.'.format(env.stack_name))

    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
        f.write(import_template(bucket, policy))
        template_path = f.name
    try:
        aws.run('cloudformation', 'create-change-set', '--stack-name', env.stack_name,
                '--change-set-name', CHANGE_SET_NAME, '--change-set-type', 'IMPORT',
                '--resources-to-import', json.dumps(resources),
                '--template-body', 'file://' + template_path)
    finally:
        os.unlink(template_path)
    aws.run('cloudformation', 'wait', 'change-set-create-complete',
            '--stack-name', env.stack_name, '--change-set-name', CHANGE_SET_NAME)
    aws.run('cloudformation', 'describe-change-set', '--stack-name', env.stack_name,
            '--change-set-name', CHANGE_SET_NAME, '--output', 'table',
            '--query', 'Changes[].ResourceChange.[Action,LogicalResourceId,PhysicalResourceId]')

    if not options.yes:
        answer = input('Import these into stack {} in {}? [y/N] '.format(env.stack_name, env.region))
        if answer.strip().lower() not in ('y', 'yes'):
            if stack is None:
                aws.run('cloudformation', 'delete-stack', '--stack-name', env.stack_name)
            else:
                aws.run('cloudformation', 'delete-change-set', '--stack-name', env.stack_name,
                        '--change-set-name', CHANGE_SET_NAME)
            print('Cancelled; nothing was imported and the bucket is untouched.', file=sys.stderr)
            return

    aws.run('cloudformation', 'execute-change-set', '--stack-name', env.stack_name,
            '--change-set-name', CHANGE_SET_NAME)
    aws.run('cloudformation', 'wait', 'stack-import-complete', '--stack-name', env.stack_name)
    print('Imported {} into stack {}.  Next, set the signing key (scripts/signing-key) and run '
          'scripts/deploy --env {} --apply-local-changes (the stack has no parameter values yet).'.format(
              ', '.join(r['LogicalResourceId'] for r in resources), env.stack_name, env.name))


if __name__ == '__main__':
    main_wrapper(main)
