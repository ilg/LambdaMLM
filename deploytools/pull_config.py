"""Create or refresh a samconfig.toml environment from its deployed stack.

    scripts/pull-config --env NAME [--overwrite-local]
    scripts/pull-config --env NAME --profile PROFILE --region REGION --stack STACK

The first form refreshes an existing environment.  The second creates one (or
points an existing one at a different stack).  If the environment already has
a value that differs from the deployed one, nothing is written unless
--overwrite-local is given.
"""

import argparse

from deploytools.common import (
        SAMCONFIG, AWS, Environment, Error, describe_stack, load_environments, main_wrapper,
        parameter_differences, save_environments, show_differences, stack_parameters)


def merge(existing, deployed, overwrite_local=False):
    """The environment's new parameters, or raise Error on conflicting local values."""
    differences = parameter_differences(existing, deployed)
    if differences and not overwrite_local:
        show_differences(differences)
        raise Error('samconfig.toml has values that differ from the deployed stack, so nothing was '
                    'written.  To replace them with the deployed values, add --overwrite-local.  To '
                    'deploy them instead, use scripts/deploy --apply-local-changes.')
    return dict(deployed)


def main(args):
    parser = argparse.ArgumentParser(prog='scripts/pull-config', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--env', required=True)
    parser.add_argument('--profile')
    parser.add_argument('--region')
    parser.add_argument('--stack')
    parser.add_argument('--overwrite-local', action='store_true')
    options = parser.parse_args(args)

    environments = load_environments()
    existing = environments.get(options.env)
    profile = options.profile or (existing.profile if existing else None)
    region = options.region or (existing.region if existing else None)
    stack_name = options.stack or (existing.stack_name if existing else None)
    if not (region and stack_name):
        raise Error('Environment {!r} is new, so give --profile, --region and --stack.'.format(options.env))

    stack = describe_stack(AWS(profile, region), stack_name)
    if stack is None:
        raise Error('Stack {} not found in {} (profile {}).'.format(stack_name, region, profile))
    deployed = stack_parameters(stack)
    local = existing.parameters if existing and existing.stack_name == stack_name else {}
    parameters = merge(local, deployed, options.overwrite_local)
    environments[options.env] = Environment(options.env, profile, region, stack_name, parameters)
    save_environments(environments)
    print('Wrote environment {!r} (stack {} in {}) to {}.'.format(
            options.env, stack_name, region, SAMCONFIG))


if __name__ == '__main__':
    main_wrapper(main)
