"""Test setup for the Lambda code.

The app modules create boto3 clients at import time, and `settings` reads
the environment when it's imported, so everything here must happen, in this
order, before any app module is imported:

1. Point AWS configuration at fake credentials, so no real credentials or
   profiles can ever be picked up.
2. Block every real AWS request at the botocore level.
3. Set the app's settings in the environment.
4. Put `lambda/` on the import path.
"""

import importlib
import os
import sys

# 1. Fake AWS configuration.
os.environ.pop('AWS_PROFILE', None)
os.environ.pop('AWS_SESSION_TOKEN', None)
os.environ.update({
    'AWS_ACCESS_KEY_ID': 'testing',
    'AWS_SECRET_ACCESS_KEY': 'testing',
    'AWS_DEFAULT_REGION': 'us-west-2',
    'AWS_CONFIG_FILE': os.devnull,
    'AWS_SHARED_CREDENTIALS_FILE': os.devnull,
    })

# 2. Refuse to send any request to AWS.  Clients copy the session's event
# handlers when they're created, so this must be registered before the app
# modules create theirs.
import boto3


class RealAWSRequestAttempted(Exception):
    pass


def _block_request(request, **kwargs):
    raise RealAWSRequestAttempted('Tests tried to reach AWS: {}'.format(request.url))


boto3.setup_default_session()
boto3.DEFAULT_SESSION.events.register('before-send', _block_request)

# 3. The app's settings, replacing any from the environment the tests run in.
# The `aws` fixture replaces the signing key, which otherwise comes from SSM.
for name in [n for n in os.environ if n.startswith('LAMBDAMLM_')]:
    del os.environ[name]
os.environ.update({
    'LAMBDAMLM_COMMAND_USER': 'lambda',
    'LAMBDAMLM_BUCKET': 'lambdamlm-test',
    'LAMBDAMLM_CONFIGURATION_PREFIX': 'config/',
    'LAMBDAMLM_INCOMING_PREFIX': 'incoming/',
    'LAMBDAMLM_MODERATION_PREFIX': 'moderation/',
    'LAMBDAMLM_SIGNED_VALIDITY_HOURS': '1',
    'LAMBDAMLM_SIGNING_KEY_PARAMETER': '/lambdamlm/test/signing-key',
    })

# 4. Import path.
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
LAMBDA_DIR = os.path.join(os.path.dirname(TESTS_DIR), 'lambda')
sys.path.insert(0, LAMBDA_DIR)

import pytest
import yaml
from freezegun.api import FakeDate, FakeDatetime

from fakes import FakeS3, FakeSES

# freezegun substitutes its own datetime classes, which PyYAML's safe dumper
# doesn't recognize.  Represent them exactly like the real ones.
yaml.SafeDumper.add_representer(FakeDatetime, yaml.representer.SafeRepresenter.represent_datetime)
yaml.SafeDumper.add_representer(FakeDate, yaml.representer.SafeRepresenter.represent_date)

# Import every module that creates a client now, so they're all created
# under the setup above.
import settings
import listobj
import sestools
import control
# The handler module is named `lambda`, which is a keyword.
handler_module = importlib.import_module('lambda')

# The real clients the app created, kept so tests can check they're blocked.
import_time_clients = {
    'listobj.s3': listobj.s3,
    'listobj.ses': listobj.ses,
    'sestools.s3': sestools.s3,
    'control.ses': control.ses,
    }


@pytest.fixture(autouse=True)
def aws(monkeypatch):
    """Replace every module-level AWS client with in-memory fakes, and the
    signing key (otherwise read from SSM) with a fixed one.

    This is the only place clients are swapped, so if the clients move (for
    example, to lazy creation), only this fixture needs to change.
    """
    monkeypatch.setattr(settings, 'signing_key', lambda: 'test signing key')
    log = []
    s3 = FakeS3(log)
    ses = FakeSES(log)
    monkeypatch.setattr(listobj, 's3', s3)
    monkeypatch.setattr(listobj, 'ses', ses)
    monkeypatch.setattr(sestools, 's3', s3)
    monkeypatch.setattr(control, 'ses', ses)
    return FakeAWS(s3=s3, ses=ses, log=log)


class FakeAWS:
    def __init__(self, s3, ses, log):
        self.s3 = s3
        self.ses = ses
        # Every S3 and SES call, in order (see fakes.FakeS3.log).
        self.log = log


@pytest.fixture
def lambda_handler():
    return handler_module.lambda_handler
