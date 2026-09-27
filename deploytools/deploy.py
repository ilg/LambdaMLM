"""Build and deploy LambdaMLM with AWS SAM.

    scripts/deploy --env NAME [--apply-local-changes] [sam deploy options...]
    scripts/deploy --profile PROFILE --region REGION --stack NAME [sam deploy options...]

With --env, the environment comes from samconfig.toml.  With --profile,
--region and --stack instead, an existing stack is redeployed with exactly
the parameter values it already has.

For an existing stack, the deployed parameter values are the starting point.
If samconfig.toml gives a different value for any of them, nothing is
deployed: the differences are listed, and you choose either to deploy the
local values (--apply-local-changes) or to take the deployed ones
(scripts/pull-config --env NAME --overwrite-local).

Needs the AWS CLI, the SAM CLI and Docker (the function is built in SAM's
Lambda build image).  Other options go to `sam deploy`; by default it shows
the change set and asks before applying it.
"""

import argparse
import os
import shutil
import subprocess
import sys

from deploytools.common import (
        ROOT, STACK_TAG, TEMPLATE, Environment, Error, aws_for, describe_stack,
        load_environment, main_wrapper, parameter_differences, show_differences,
        stack_parameters, template_parameters)

LAMBDA_DIR = os.path.join(ROOT, 'lambda')
BUILD_SRC = os.path.join(ROOT, 'build', 'src')
BUILD_DIR = os.path.join(ROOT, '.aws-sam', 'build')


def stage(source=LAMBDA_DIR, destination=BUILD_SRC):
    """Copy the function's code and requirements.txt for building.

    Leaves out config files from the old fabfile deployments (config*.py),
    dotfiles, caches and editor files.
    """
    def ignore(directory, names):
        ignored = []
        for name in names:
            if name.startswith('.') or name == '__pycache__' or name.endswith(('.pyc', '.swp', '~')):
                ignored.append(name)
            elif (os.path.abspath(directory) == os.path.abspath(source)
                  and name.startswith('config') and name.endswith('.py')):
                ignored.append(name)
        return ignored

    if os.path.exists(destination):
        shutil.rmtree(destination)
    shutil.copytree(source, destination, ignore=ignore)


def plan_parameters(local, deployed, apply_local_changes=False, known=None):
    """The parameter values to deploy with.

    local: values from samconfig.toml; deployed: the stack's current values, or
    None for a new stack.  Raises Error if they disagree and
    apply_local_changes isn't set.  Parameters the template no longer has are
    dropped.
    """
    if deployed is None:
        params = dict(local)
    else:
        differences = parameter_differences(local, deployed)
        if differences and not apply_local_changes:
            show_differences(differences)
            raise Error('samconfig.toml disagrees with the deployed stack, so nothing was deployed.\n'
                        'To deploy the samconfig.toml values: scripts/deploy ... --apply-local-changes\n'
                        'To keep the deployed values: scripts/pull-config --env NAME --overwrite-local')
        params = dict(deployed)
        if apply_local_changes:
            params.update(local)
    if known is not None:
        params = {k: v for k, v in params.items() if k in known}
    return params


def override_arguments(params):
    """Parameter values as `sam deploy --parameter-overrides` arguments.

    Values are quoted, so empty values and values with spaces survive SAM's parser.
    """
    return ['{}="{}"'.format(k, v.replace('\\', '\\\\').replace('"', '\\"')) for k, v in sorted(params.items())]


def ensure_rule_set(aws, name):
    """Create the SES receipt rule set if it doesn't exist yet."""
    if aws.succeeds('ses', 'describe-receipt-rule-set', '--rule-set-name', name):
        return
    aws.run('ses', 'create-receipt-rule-set', '--rule-set-name', name)


def activate_rule_set_if_none(aws, name):
    """Make the rule set active, unless another one already is.

    Only one rule set per region can be active, so activating ours would
    switch off another deployment's receipt rules.
    """
    active = (aws.json('ses', 'describe-active-receipt-rule-set').get('Metadata') or {}).get('Name')
    if not active:
        aws.run('ses', 'set-active-receipt-rule-set', '--rule-set-name', name)
    elif active != name:
        print('Note: the active SES receipt rule set is {!r}, not {!r}, so the receipt rule '
              "won't receive mail until {!r} is active.".format(active, name, name), file=sys.stderr)


def parse_args(args):
    parser = argparse.ArgumentParser(prog='scripts/deploy', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--env')
    parser.add_argument('--profile')
    parser.add_argument('--region')
    parser.add_argument('--stack')
    parser.add_argument('--apply-local-changes', action='store_true')
    options, sam_args = parser.parse_known_args(args)
    if options.env:
        if options.profile or options.region or options.stack:
            parser.error('use either --env or --profile/--region/--stack')
        env = load_environment(options.env)
    elif options.region and options.stack:
        env = Environment(None, options.profile, options.region, options.stack)
    else:
        parser.error('give --env, or --profile, --region and --stack')
    return env, options.apply_local_changes, sam_args


def main(args):
    env, apply_local_changes, sam_args = parse_args(args)
    aws = aws_for(env)
    stack = describe_stack(aws, env.stack_name)
    if stack is None and env.name is None:
        raise Error('Stack {} not found in {}.  For a new deployment, use an environment in '
                    'samconfig.toml (see samconfig.example.toml).'.format(env.stack_name, env.region))
    deployed = stack_parameters(stack) if stack else None
    params = plan_parameters(env.parameters, deployed, apply_local_changes, set(template_parameters()))
    if stack is None:
        if not params.get('BucketName'):
            raise Error('A new deployment needs BucketName in its samconfig.toml parameters.')
        print('Stack {} does not exist in {}; this creates it.'.format(env.stack_name, env.region),
              file=sys.stderr)

    if not aws.succeeds('ssm', 'get-parameter', '--name', env.signing_key_parameter):
        raise Error('The signing key {} is not set.  Create it first with scripts/signing-key '
                    '(generate, set or import-from-function).'.format(env.signing_key_parameter))

    stage()
    subprocess.run(['sam', 'build', '--use-container', '--template-file', TEMPLATE,
                    '--build-dir', BUILD_DIR], check=True)

    rule_set = params.get('ReceiptRuleSetName')
    if rule_set:
        ensure_rule_set(aws, rule_set)
    if not any(a in sam_args for a in ('--confirm-changeset', '--no-confirm-changeset')):
        sam_args = ['--confirm-changeset'] + sam_args
    command = ['sam', 'deploy',
               '--template-file', os.path.join(BUILD_DIR, 'template.yaml'),
               '--stack-name', env.stack_name,
               '--region', env.region,
               '--resolve-s3',
               '--capabilities', 'CAPABILITY_IAM',
               '--no-fail-on-empty-changeset',
               '--tags', '{}={}'.format(*STACK_TAG)]
    if env.profile:
        command += ['--profile', env.profile]
    if params:
        command += ['--parameter-overrides'] + override_arguments(params)
    print('+ ' + ' '.join(command + sam_args), file=sys.stderr)
    subprocess.run(command + sam_args, check=True)
    if rule_set:
        activate_rule_set_if_none(aws, rule_set)


if __name__ == '__main__':
    main_wrapper(main)
