"""Adopt an existing deployment's S3 bucket into a new LambdaMLM stack.

    scripts/import-bucket --env NAME [--yes]

Run this once, before the first scripts/deploy, when moving a deployment made
with the old fabfile to a SAM stack.  It creates the environment's stack
containing only the bucket named by the environment's BucketName, without
changing the bucket or anything in it.  scripts/deploy then adds the rest of
the stack and applies the template's bucket settings.

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


def import_template(bucket):
    """A template holding only the bucket, as the full template declares it."""
    return json.dumps({
        'AWSTemplateFormatVersion': '2010-09-09',
        'Description': 'LambdaMLM: importing the existing bucket.  scripts/deploy adds the rest.',
        'Resources': {
            'MailBucket': {
                'Type': 'AWS::S3::Bucket',
                'DeletionPolicy': 'Retain',
                'UpdateReplacePolicy': 'Retain',
                'Properties': {'BucketName': bucket},
            },
        },
    }, indent=2)


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
    if describe_stack(aws, env.stack_name) is not None:
        raise Error('Stack {} already exists, so there is nothing to import.'.format(env.stack_name))
    if not aws.succeeds('s3api', 'head-bucket', '--bucket', bucket):
        raise Error("Bucket {} doesn't exist (or isn't yours), so there is nothing to import.  "
                    'For a new deployment, just run scripts/deploy.'.format(bucket))

    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
        f.write(import_template(bucket))
        template_path = f.name
    try:
        resources = [{'ResourceType': 'AWS::S3::Bucket', 'LogicalResourceId': 'MailBucket',
                      'ResourceIdentifier': {'BucketName': bucket}}]
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
        answer = input('Import bucket {} into new stack {} in {}? [y/N] '.format(bucket, env.stack_name, env.region))
        if answer.strip().lower() not in ('y', 'yes'):
            aws.run('cloudformation', 'delete-stack', '--stack-name', env.stack_name)
            print('Cancelled; the pending stack was removed and the bucket is untouched.', file=sys.stderr)
            return

    aws.run('cloudformation', 'execute-change-set', '--stack-name', env.stack_name,
            '--change-set-name', CHANGE_SET_NAME)
    aws.run('cloudformation', 'wait', 'stack-import-complete', '--stack-name', env.stack_name)
    print('Imported {} into stack {}.  Next, set the signing key (scripts/signing-key) and run '
          'scripts/deploy --env {}.'.format(bucket, env.stack_name, env.name))


if __name__ == '__main__':
    main_wrapper(main)
