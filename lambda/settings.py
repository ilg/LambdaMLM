"""The function's settings.

They come from environment variables, which template.yaml sets from the
stack's parameters, except the command-signing key, which is read from SSM
Parameter Store the first time it's needed.
"""

import os
from datetime import timedelta

import aws_clients

# The user part of the address commands are sent to (lambda@<list host>).
command_user = os.environ.get('LAMBDAMLM_COMMAND_USER', 'lambda')

# The S3 bucket holding list configurations, incoming mail and held messages,
# and the key prefixes for each.
s3_bucket = os.environ.get('LAMBDAMLM_BUCKET', '')
s3_configuration_prefix = os.environ.get('LAMBDAMLM_CONFIGURATION_PREFIX', 'config/')
s3_incoming_email_prefix = os.environ.get('LAMBDAMLM_INCOMING_PREFIX', 'incoming/')
s3_moderation_prefix = os.environ.get('LAMBDAMLM_MODERATION_PREFIX', 'moderation/')

# How long a signed command stays valid.
signed_validity_interval = timedelta(hours=float(os.environ.get('LAMBDAMLM_SIGNED_VALIDITY_HOURS', '1')))

# The SSM parameter (a SecureString) holding the command-signing key.
signing_key_parameter = os.environ.get('LAMBDAMLM_SIGNING_KEY_PARAMETER', '')

_signing_key = None


def signing_key():
    """The command-signing key, read from SSM once per container."""
    global _signing_key
    if _signing_key is None:
        response = aws_clients.ssm().get_parameter(Name=signing_key_parameter, WithDecryption=True)
        _signing_key = response['Parameter']['Value']
    return _signing_key
