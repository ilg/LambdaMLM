"""Checks that the test harness itself is set up safely."""

import os
import sys

import boto3
import pytest
from botocore.client import BaseClient

import settings
import control
import listobj
import sestools
from conftest import (
        LAMBDA_DIR, RealAWSRequestAttempted, handler_module, import_time_clients)
from fakes import FakeS3, FakeSES


def test_settings_are_the_fake():
    assert settings.s3_bucket == 'lambdamlm-test'


def test_module_clients_are_fakes(aws):
    assert listobj.s3 is aws.s3
    assert sestools.s3 is aws.s3
    assert isinstance(aws.s3, FakeS3)
    assert listobj.ses is aws.ses
    assert control.ses is aws.ses
    assert isinstance(aws.ses, FakeSES)


def test_handler_module_imports():
    assert callable(handler_module.lambda_handler)


def test_real_aws_requests_are_blocked():
    client = boto3.client('s3')
    with pytest.raises(RealAWSRequestAttempted):
        client.get_object(Bucket='lambdamlm-test', Key='anything')


def test_fake_s3_returns_bytes_stream(aws):
    aws.s3.put('bucket', 'key', 'café')
    body = aws.s3.get_object(Bucket='bucket', Key='key')['Body']
    assert body.read(3) == b'caf'
    assert body.read() == 'é'.encode('utf-8')
    assert body.read() == b''


@pytest.mark.parametrize('name', sorted(import_time_clients))
def test_import_time_clients_are_blocked(name):
    client = import_time_clients[name]
    with pytest.raises(RealAWSRequestAttempted):
        if client.meta.service_model.service_name == 's3':
            client.get_object(Bucket='lambdamlm-test', Key='anything')
        else:
            client.send_email(
                    Source='a@example.com',
                    Destination={'ToAddresses': ['b@example.com']},
                    Message={'Subject': {'Data': 's'}, 'Body': {'Text': {'Data': 'b'}}},
                    )


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
    assert {'listobj', 'sestools', 'control', 'lambda'} <= scanned
    assert leftovers == []
