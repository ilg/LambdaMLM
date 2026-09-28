"""The real lambda/settings.py: environment variables and the SSM signing key."""

import importlib.util
import os
from datetime import timedelta

import boto3

from helpers import TESTS_DIR

SETTINGS = os.path.join(os.path.dirname(TESTS_DIR), 'lambda', 'settings.py')


def load(monkeypatch, **environment):
    for name in [n for n in os.environ if n.startswith('LAMBDAMLM_')]:
        monkeypatch.delenv(name)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    # Load it under another name; the tests' fake is installed as `settings`.
    spec = importlib.util.spec_from_file_location('real_settings', SETTINGS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_defaults(monkeypatch):
    s = load(monkeypatch)
    assert s.command_user == 'lambda'
    assert (s.s3_configuration_prefix, s.s3_incoming_email_prefix, s.s3_moderation_prefix) == (
        'config/', 'incoming/', 'moderation/')
    assert s.signed_validity_interval == timedelta(hours=1)


def test_from_environment(monkeypatch):
    s = load(monkeypatch, LAMBDAMLM_COMMAND_USER='lists', LAMBDAMLM_BUCKET='b',
             LAMBDAMLM_CONFIGURATION_PREFIX='c/', LAMBDAMLM_INCOMING_PREFIX='i/',
             LAMBDAMLM_MODERATION_PREFIX='m/', LAMBDAMLM_SIGNED_VALIDITY_HOURS='0.5',
             LAMBDAMLM_SIGNING_KEY_PARAMETER='/lambdamlm/prod/signing-key')
    assert (s.command_user, s.s3_bucket, s.s3_configuration_prefix, s.s3_incoming_email_prefix,
            s.s3_moderation_prefix) == ('lists', 'b', 'c/', 'i/', 'm/')
    assert s.signed_validity_interval == timedelta(minutes=30)
    assert s.signing_key_parameter == '/lambdamlm/prod/signing-key'


class FakeSSM:
    def __init__(self):
        self.calls = []

    def get_parameter(self, Name, WithDecryption):
        self.calls.append((Name, WithDecryption))
        return {'Parameter': {'Name': Name, 'Value': 'key with a backslash \\ and é'}}


def test_signing_key_is_read_from_ssm_once(monkeypatch):
    s = load(monkeypatch, LAMBDAMLM_SIGNING_KEY_PARAMETER='/lambdamlm/prod/signing-key')
    ssm = FakeSSM()
    monkeypatch.setattr(boto3, 'client', lambda service: ssm if service == 'ssm' else None)
    assert s.signing_key() == 'key with a backslash \\ and é'
    assert s.signing_key() == 'key with a backslash \\ and é'
    assert ssm.calls == [('/lambdamlm/prod/signing-key', True)]
