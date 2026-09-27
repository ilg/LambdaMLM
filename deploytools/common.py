"""Shared pieces of the deployment scripts: environments, the AWS CLI, stacks.

A deployment is a CloudFormation stack, and the stack is the source of truth
for its settings.  samconfig.toml (gitignored; see samconfig.example.toml)
keeps named environments -- AWS profile, region, stack name and parameter
values -- as a convenience.  scripts/pull-config can always rebuild an
environment from its stack.
"""

import json
import os
import subprocess
import sys

try:
    import tomllib
except ImportError:  # Python < 3.11
    sys.exit('These scripts need Python 3.11 or later.')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMCONFIG = os.path.join(ROOT, 'samconfig.toml')
TEMPLATE = os.path.join(ROOT, 'template.yaml')
STACK_TAG = ('lambdamlm', 'true')


class Error(Exception):
    """A problem to report to the user, without a traceback."""


# ---------------------------------------------------------------- environments

class Environment(object):
    """A named deployment: where it is, and (optionally) its parameter values."""

    def __init__(self, name, profile, region, stack_name, parameters=None):
        self.name = name
        self.profile = profile
        self.region = region
        self.stack_name = stack_name
        self.parameters = dict(parameters or {})

    def __repr__(self):
        return 'Environment({!r}, {!r}, {!r}, {!r})'.format(
                self.name, self.profile, self.region, self.stack_name)

    @property
    def signing_key_parameter(self):
        return signing_key_parameter(self.stack_name)


def signing_key_parameter(stack_name):
    return '/lambdamlm/{}/signing-key'.format(stack_name)


def _parse_overrides(value):
    """samconfig's parameter_overrides: a list of Key=Value, or one string of them."""
    if isinstance(value, str):
        import shlex
        value = shlex.split(value)
    result = {}
    for item in value or []:
        key, _, val = item.partition('=')
        result[key] = val
    return result


def load_environments(path=SAMCONFIG):
    if not os.path.exists(path):
        return {}
    with open(path, 'rb') as f:
        data = tomllib.load(f)
    environments = {}
    for name, sections in data.items():
        if not isinstance(sections, dict):
            continue
        params = sections.get('deploy', {}).get('parameters', {})
        if 'stack_name' not in params:
            continue
        environments[name] = Environment(
                name, params.get('profile'), params.get('region'), params['stack_name'],
                _parse_overrides(params.get('parameter_overrides')))
    return environments


def load_environment(name, path=SAMCONFIG):
    environments = load_environments(path)
    if name not in environments:
        raise Error('No environment {!r} in {}.  Environments: {}.  (scripts/pull-config can create '
                    'one from a deployed stack.)'.format(name, path, ', '.join(sorted(environments)) or 'none'))
    return environments[name]


def _toml_string(value):
    return json.dumps(value, ensure_ascii=False)


def render_environments(environments):
    """samconfig.toml text for the environments, in SAM's format."""
    lines = ['# LambdaMLM deployment environments; see samconfig.example.toml.',
             '# The deployed stacks are the source of truth: scripts/pull-config',
             '# rebuilds an environment from its stack.',
             'version = 0.1']
    for name in sorted(environments):
        env = environments[name]
        lines += ['', '[{}.deploy.parameters]'.format(name),
                  'stack_name = {}'.format(_toml_string(env.stack_name))]
        if env.profile:
            lines.append('profile = {}'.format(_toml_string(env.profile)))
        if env.region:
            lines.append('region = {}'.format(_toml_string(env.region)))
        if env.parameters:
            lines.append('parameter_overrides = [')
            lines += ['    {},'.format(_toml_string('{}={}'.format(k, v)))
                      for k, v in sorted(env.parameters.items())]
            lines.append(']')
    return '\n'.join(lines) + '\n'


def save_environments(environments, path=SAMCONFIG):
    with open(path, 'w') as f:
        f.write(render_environments(environments))


# ---------------------------------------------------------------- AWS CLI

class AWS(object):
    """Runs AWS CLI commands for one profile and region."""

    def __init__(self, profile, region):
        self.profile = profile
        self.region = region

    def _base(self):
        command = ['aws']
        if self.profile:
            command += ['--profile', self.profile]
        if self.region:
            command += ['--region', self.region]
        return command

    def json(self, *args, input=None, check=True):
        """Run a command and return its parsed JSON output (or None if it failed and check=False)."""
        result = subprocess.run(self._base() + list(args) + ['--output', 'json'],
                                capture_output=True, text=True, input=input)
        if result.returncode != 0:
            if check:
                raise Error('aws {} failed: {}'.format(' '.join(args[:2]), result.stderr.strip()))
            return None
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def succeeds(self, *args):
        return subprocess.run(self._base() + list(args), capture_output=True).returncode == 0

    def run(self, *args):
        """Run a command, showing it and its output."""
        command = self._base() + list(args)
        print('+ ' + ' '.join(command), file=sys.stderr)
        subprocess.run(command, check=True)


def aws_for(env):
    return AWS(env.profile, env.region)


# ---------------------------------------------------------------- stacks

def describe_stack(aws, stack_name):
    """The stack's description, or None if it doesn't exist."""
    try:
        result = aws.json('cloudformation', 'describe-stacks', '--stack-name', stack_name)
    except Error as e:
        # Report any other failure, such as expired credentials, as it is.
        if 'does not exist' in str(e):
            return None
        raise
    return result['Stacks'][0]


def stack_parameters(stack):
    return {p['ParameterKey']: p.get('ParameterValue', '') for p in stack.get('Parameters', [])}


def stack_outputs(stack):
    return {o['OutputKey']: o['OutputValue'] for o in stack.get('Outputs', [])}


def template_parameters(path=TEMPLATE):
    """Names of the template's parameters (read without a YAML library)."""
    names = []
    in_parameters = False
    with open(path) as f:
        for line in f:
            if line.startswith('Parameters:'):
                in_parameters = True
            elif in_parameters and line and not line[0].isspace() and line.strip():
                break
            elif in_parameters and line.startswith('  ') and not line.startswith('   ') and line.strip().endswith(':'):
                names.append(line.strip()[:-1])
    return names


def parameter_differences(local, deployed):
    """{name: (deployed value, local value)} for local values that differ."""
    return {k: (deployed.get(k), v) for k, v in local.items() if deployed.get(k) != v}


def show_differences(differences, local_label='samconfig.toml', deployed_label='deployed'):
    width = max(len(k) for k in differences)
    for key, (deployed, local) in sorted(differences.items()):
        print('  {:{w}}  {}: {!r}   {}: {!r}'.format(
                key, deployed_label, deployed, local_label, local, w=width), file=sys.stderr)


def main_wrapper(main):
    """Run a script's main(args), reporting Error without a traceback."""
    try:
        main(sys.argv[1:])
    except Error as e:
        sys.exit(str(e))
    except subprocess.CalledProcessError as e:
        sys.exit('Command failed with exit status {}.'.format(e.returncode))
