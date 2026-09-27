"""Manage a deployment's command-signing key in SSM Parameter Store.

    scripts/signing-key generate --env NAME [--force]
    scripts/signing-key set --env NAME [--force]
    scripts/signing-key import-from-function --env NAME --function FUNCTION
                        [--function-profile PROFILE] [--function-region REGION] [--force]
    scripts/signing-key check --env NAME

The key is the SecureString parameter /lambdamlm/<stack name>/signing-key.
It's never printed; `check` shows a fingerprint (an HMAC of a fixed string, so
the same key always has the same fingerprint) and has the deployed function
verify a command signed with the stored key.

generate  stores a new random key.
set       prompts for a key (without echoing it) and stores it.
import-from-function
          copies the key from an old fabfile-era deployment: it reads the
          signing_key from the config.py packaged in that Lambda function.
check     shows the stored key's fingerprint, then asks the deployed function
          (through its VerifySignedCommand API action) to check a command
          signed with the stored key, and a tampered copy of it.

Replacing a key invalidates every outstanding invitation and signed command,
so generate, set and import-from-function refuse to replace an existing key
unless given --force.

Deployments are named by --env (samconfig.toml), or by --profile, --region
and --stack.
"""

import argparse
import base64
import datetime
import getpass
import hashlib
import hmac
import io
import json
import os
import runpy
import secrets
import tempfile
import urllib.request
import warnings
import zipfile

from deploytools.common import (
        AWS, Environment, Error, aws_for, describe_stack, load_environment, main_wrapper,
        stack_outputs)

TIMESTAMP_FORMAT = '%Y%m%d%H%M%S'
CHECK_ADDRESS = 'signing-key-check@example.invalid'


# ---------------------------------------------------------------- signing
# The same algorithm as lambda/control (tests/test_deploy.py checks they agree).

def signature(key, text):
    key = key if isinstance(key, bytes) else key.encode('utf-8')
    digest = hmac.new(key, text.strip().encode('utf-8'), hashlib.sha1).digest()
    return base64.b64encode(digest).decode('ascii')


def sign(key, command, address, expires):
    timestamp = expires.strftime(TIMESTAMP_FORMAT)
    return '{} {}{}'.format(command, signature(key, ' '.join([address, timestamp, command])), timestamp)


def fingerprint(key):
    key = key if isinstance(key, bytes) else key.encode('utf-8')
    return hmac.new(key, b'LambdaMLM signing key fingerprint', hashlib.sha256).hexdigest()[:16]


# ---------------------------------------------------------------- SSM

def key_exists(aws, name):
    return aws.succeeds('ssm', 'get-parameter', '--name', name)


def read_key(aws, name):
    result = aws.json('ssm', 'get-parameter', '--name', name, '--with-decryption')
    return result['Parameter']['Value']


def store_key(aws, name, key, force):
    if key_exists(aws, name) and not force:
        raise Error('{} already has a key.  Replacing it invalidates outstanding invitations and '
                    'signed commands; add --force to do it anyway.'.format(name))
    request = {'Name': name, 'Value': key, 'Type': 'SecureString', 'Overwrite': True,
               'Description': 'LambdaMLM command-signing key'}
    # The key goes to the AWS CLI in a file only the user can read, deleted
    # straight afterwards, so it never appears in a process listing.
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, 'request.json')
        with open(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600), 'w') as f:
            json.dump(request, f)
        aws.json('ssm', 'put-parameter', '--cli-input-json', 'file://' + path)
    print('Stored the key in {} (fingerprint {}).'.format(name, fingerprint(key)))


def key_from_function(aws, function):
    """The signing_key from the config.py packaged in a fabfile-era Lambda function."""
    location = aws.json('lambda', 'get-function', '--function-name', function)['Code']['Location']
    with urllib.request.urlopen(location) as response:
        package = zipfile.ZipFile(io.BytesIO(response.read()))
    if 'config.py' not in package.namelist():
        raise Error('{} has no config.py, so it has no key to import.'.format(function))
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, 'config.py')
        with open(path, 'wb') as f:
            f.write(package.read('config.py'))
        with warnings.catch_warnings():
            # Old keys can contain backslashes that Python 3 warns about.
            warnings.simplefilter('ignore')
            settings = runpy.run_path(path)
    if not settings.get('signing_key'):
        raise Error("{}'s config.py has no signing_key.".format(function))
    return settings['signing_key']


# ---------------------------------------------------------------- commands

def check(aws, env):
    key = read_key(aws, env.signing_key_parameter)
    print('Stored key fingerprint: {}'.format(fingerprint(key)))
    stack = describe_stack(aws, env.stack_name)
    if stack is None:
        raise Error('Stack {} not found, so there is no function to check against.'.format(env.stack_name))
    function = stack_outputs(stack)['FunctionName']
    # The function runs in UTC.
    expires = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(minutes=10)
    signed = sign(key, 'about', CHECK_ADDRESS, expires)
    cases = [('a command signed with the stored key', signed, 'Valid'),
             ('the same command, tampered with', signed.replace('about', 'abort', 1), 'Invalid')]
    ok = True
    for description, subject, expected in cases:
        payload = {'Action': 'VerifySignedCommand', 'Subject': subject, 'Address': CHECK_ADDRESS}
        with tempfile.NamedTemporaryFile('r') as out:
            aws.json('lambda', 'invoke', '--function-name', function,
                     '--cli-binary-format', 'raw-in-base64-out',
                     '--payload', json.dumps(payload), out.name)
            response = json.load(open(out.name))
        result = (response.get('Data') or {}).get('Result', response)
        print('  {}: {} (expected {})'.format(description, result, expected))
        ok = ok and result == expected
    if not ok:
        raise Error('The deployed function did not validate signatures as expected.')
    print('The deployed function {} validates signatures made with the stored key.'.format(function))


def main(args):
    parser = argparse.ArgumentParser(prog='scripts/signing-key', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=['generate', 'set', 'import-from-function', 'check'])
    parser.add_argument('--env')
    parser.add_argument('--profile')
    parser.add_argument('--region')
    parser.add_argument('--stack')
    parser.add_argument('--function')
    parser.add_argument('--function-profile')
    parser.add_argument('--function-region')
    parser.add_argument('--force', action='store_true')
    options = parser.parse_args(args)
    if options.env:
        env = load_environment(options.env)
    elif options.region and options.stack:
        env = Environment(None, options.profile, options.region, options.stack)
    else:
        parser.error('give --env, or --profile, --region and --stack')
    aws = aws_for(env)

    if options.command == 'generate':
        store_key(aws, env.signing_key_parameter, secrets.token_urlsafe(32), options.force)
    elif options.command == 'set':
        key = getpass.getpass('Signing key: ')
        if not key or key != getpass.getpass('Again: '):
            raise Error("The keys were empty or didn't match; nothing was stored.")
        store_key(aws, env.signing_key_parameter, key, options.force)
    elif options.command == 'import-from-function':
        if not options.function:
            parser.error('import-from-function needs --function')
        source = AWS(options.function_profile or env.profile, options.function_region or env.region)
        key = key_from_function(source, options.function)
        print('Key in {}: fingerprint {}.'.format(options.function, fingerprint(key)))
        store_key(aws, env.signing_key_parameter, key, options.force)
    else:
        check(aws, env)


if __name__ == '__main__':
    main_wrapper(main)
