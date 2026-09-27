# -*- coding: utf-8 -*-
"""Test setup for the Lambda code.

The app modules create boto3 clients and read `config` at import time, so
everything here must happen, in this order, before any app module is
imported:

1. Point AWS configuration at fake credentials, so no real credentials or
   profiles can ever be picked up.
2. Block every real AWS request at the botocore level.
3. Install a fake `config` module.
4. Put `lambda/` on the import path.
"""

import importlib
import os
import sys
import types
from datetime import timedelta

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

# 3. Fake config module, mirroring config.example.py.  The signing key is a
# native (non-unicode) string: on Python 2 a unicode key crashes signing
# (issue #34), which is pinned separately.
config = types.ModuleType('config')
config.command_user = 'lambda'
config.lambda_region = 'us-west-2'
config.lambda_name = 'LambdaMLM'
config.iam_role_name = 'LambdaMLM'
config.s3_bucket = 'lambdamlm-test'
config.s3_incoming_email_prefix = 'incoming/'
config.s3_configuration_prefix = 'config/'
config.s3_moderation_prefix = 'moderation/'
config.signing_key = 'test signing key'
config.signed_validity_interval = timedelta(hours=1)
sys.modules['config'] = config

# 4. Import path.
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
LAMBDA_DIR = os.path.join(os.path.dirname(TESTS_DIR), 'lambda')
sys.path.insert(0, LAMBDA_DIR)

import pytest

from fakes import FakeS3, FakeSES

# Import every module that creates a client now, so they're all created
# under the setup above.
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
    """Replace every module-level AWS client with in-memory fakes.

    This is the only place clients are swapped, so if the clients move (for
    example, to lazy creation), only this fixture needs to change.
    """
    s3 = FakeS3()
    ses = FakeSES()
    monkeypatch.setattr(listobj, 's3', s3)
    monkeypatch.setattr(listobj, 'ses', ses)
    monkeypatch.setattr(sestools, 's3', s3)
    monkeypatch.setattr(control, 'ses', ses)
    return FakeAWS(s3=s3, ses=ses)


class FakeAWS(object):
    def __init__(self, s3, ses):
        self.s3 = s3
        self.ses = ses


@pytest.fixture
def lambda_handler():
    return handler_module.lambda_handler
