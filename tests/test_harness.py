"""Checks that the test harness itself is set up safely."""

import importlib
import json
import os
import subprocess
import sys

import boto3
import pytest
from botocore.client import BaseClient

import aws_clients
import settings
from conftest import (
        LAMBDA_DIR, REAL_CLIENT_ACCESSORS, RealAWSClientCreated, RealAWSRequestAttempted,
        handler_module)
from fakes import FakeS3, FakeSES


def test_settings_are_the_fake():
    assert settings.s3_bucket == 'lambdamlm-test'


def test_clients_are_fakes(aws):
    assert aws_clients.s3() is aws.s3
    assert isinstance(aws.s3, FakeS3)
    assert aws_clients.ses() is aws.ses
    assert isinstance(aws.ses, FakeSES)


def test_creating_real_clients_fails(aws):
    with pytest.raises(RealAWSClientCreated):
        boto3.client('s3')
    with pytest.raises(RealAWSClientCreated):
        aws_clients.ssm()


def test_handler_module_imports():
    assert callable(handler_module.lambda_handler)


def test_template_uses_the_handler():
    with open(os.path.join(os.path.dirname(LAMBDA_DIR), 'template.yaml')) as f:
        assert '      Handler: handler.lambda_handler\n' in f.read()


def test_old_handler_name_still_works():
    # lambda.py stays for a release, for mail that arrives while a deploy has
    # updated the code but not yet the handler setting.  `lambda` is a keyword,
    # so it can only be imported like this.
    assert importlib.import_module('lambda').lambda_handler is handler_module.lambda_handler


def test_each_client_is_created_once(monkeypatch):
    created = []
    monkeypatch.setattr(boto3, 'client', lambda service: created.append(service) or object())
    for service, accessor in REAL_CLIENT_ACCESSORS.items():
        accessor.cache_clear()
        try:
            assert accessor() is accessor()
        finally:
            accessor.cache_clear()
    assert created == ['s3', 'ses', 'ssm']


def test_real_aws_requests_are_blocked():
    # A second line of defense, for a client created despite the fixture.
    client = boto3.DEFAULT_SESSION.client('s3')
    with pytest.raises(RealAWSRequestAttempted):
        client.get_object(Bucket='lambdamlm-test', Key='anything')


def test_fake_s3_returns_bytes_stream(aws):
    aws.s3.put('bucket', 'key', 'café')
    body = aws.s3.get_object(Bucket='bucket', Key='key')['Body']
    assert body.read(3) == b'caf'
    assert body.read() == 'é'.encode('utf-8')
    assert body.read() == b''


IMPORT_APP = """
import importlib, json, sys
import boto3, boto3.session

def fail(*args, **kwargs):
    raise SystemExit('Importing the app created an AWS client: {}'.format(args))
boto3.client = fail
boto3.session.Session.client = fail

sys.path.insert(0, sys.argv[1])
importlib.import_module('handler')
# Only the handler is imported, as in Lambda, so this shows which commands
# its imports register.
root = sys.modules['control.commands'].command
list_group = root.commands['list']
print(json.dumps({
    'root': sorted(root.commands),
    'list': sorted(list_group.commands),
    'mod': sorted(list_group.commands['mod'].commands),
    }))
"""


def test_importing_the_app_has_no_side_effects():
    # In a fresh interpreter, since this one has imported the app already.
    result = subprocess.run([sys.executable, '-c', IMPORT_APP, LAMBDA_DIR],
                            capture_output=True, text=True, env=dict(os.environ))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        'root': ['about', 'echo', 'list'],
        'list': ['accept_subscription_invitation', 'accept_unsubscription_invitation',
                 'members', 'mod', 'set', 'setflag', 'subscribe', 'unsetflag', 'unsubscribe'],
        'mod': ['approve', 'reject'],
        }


def test_no_real_clients_left_in_app_modules(aws):
    # Catches a new module-level client that the `aws` fixture doesn't replace.
    leftovers = []
    scanned = set()
    for module_name, module in list(sys.modules.items()):
        module_file = getattr(module, '__file__', None) or ''
        if not os.path.abspath(module_file).startswith(LAMBDA_DIR + os.sep):
            continue
        scanned.add(module_name)
        for attr, value in vars(module).items():
            if isinstance(value, BaseClient):
                leftovers.append('{}.{}'.format(module_name, attr))
    assert {'aws_clients', 'listobj', 'sestools', 'control', 'handler'} <= scanned
    assert leftovers == []
