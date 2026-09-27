# -*- coding: utf-8 -*-
"""The deployment tools: packaging, environments, parameters and signing keys."""

import datetime
import io
import json
import os
import zipfile

import pytest
from freezegun import freeze_time

import control
from deploytools import common, deploy, import_bucket, pull_config, signing_key
from helpers import TESTS_DIR

ROOT = os.path.dirname(TESTS_DIR)


def write(path, text=''):
    if not os.path.isdir(os.path.dirname(path)):
        os.makedirs(os.path.dirname(path))
    with open(path, 'w') as f:
        f.write(text)


# ---------------------------------------------------------------- packaging

def test_stage_packages_code_only(tmp_path):
    source = tmp_path / 'lambda'
    for name in ['lambda.py', 'settings.py', 'config.py', 'config.example.py', 'config.prod.py',
                 'requirements.txt', '.lambda.py.swp', 'x.pyc', '__pycache__/y.pyc', 'api/actions.py',
                 'api/.actions.py.swp', 'api/notes~', 'templates/notify_moderators.jinja2',
                 'control/config.py']:
        write(str(source / name))
    destination = tmp_path / 'build'
    deploy.stage(str(source), str(destination))
    staged = sorted(os.path.relpath(os.path.join(d, f), str(destination))
                    for d, _, files in os.walk(str(destination)) for f in files)
    assert staged == ['api/actions.py', 'control/config.py', 'lambda.py', 'requirements.txt',
                      'settings.py', 'templates/notify_moderators.jinja2']


def test_stage_real_function(tmp_path):
    destination = tmp_path / 'build'
    deploy.stage(destination=str(destination))
    for name in ('lambda.py', 'settings.py', 'listobj.py', 'lamson_bounce.py', 'requirements.txt',
                 'templates/notify_moderators.jinja2', 'control/list_commands.py', 'api/actions.py'):
        assert (destination / name).exists(), name


# ---------------------------------------------------------------- environments

def test_environments_round_trip(tmp_path):
    environments = {
        'prod': common.Environment('prod', 'default', 'us-west-2', 'LambdaMLM',
                                   {'BucketName': 'b', 'AlarmEmail': '', 'ReceiptRuleRecipients': 'a.org,b.org'}),
        'staging': common.Environment('staging', 'staging-profile', 'us-west-2', 'LambdaMLM', {'BucketName': 'c'}),
    }
    path = str(tmp_path / 'samconfig.toml')
    common.save_environments(environments, path)
    loaded = common.load_environments(path)
    assert sorted(loaded) == ['prod', 'staging']
    for name, env in environments.items():
        got = loaded[name]
        assert (got.profile, got.region, got.stack_name, got.parameters) == (
            env.profile, env.region, env.stack_name, env.parameters)
    assert loaded['prod'].signing_key_parameter == '/lambdamlm/LambdaMLM/signing-key'


def test_environment_with_string_overrides(tmp_path):
    # SAM also writes parameter_overrides as one string.
    path = tmp_path / 'samconfig.toml'
    path.write_text('version = 0.1\n[x.deploy.parameters]\nstack_name = "S"\nregion = "r"\n'
                    'parameter_overrides = "BucketName=\\"b\\" AlarmEmail=a@example.org"\n')
    assert common.load_environments(str(path))['x'].parameters == {
        'BucketName': 'b', 'AlarmEmail': 'a@example.org'}


def test_missing_environment(tmp_path):
    with pytest.raises(common.Error, match='pull-config'):
        common.load_environment('nope', str(tmp_path / 'samconfig.toml'))


def test_example_environment_uses_template_parameters():
    example = common.load_environments(os.path.join(ROOT, 'samconfig.example.toml'))['example']
    assert set(example.parameters) <= set(common.template_parameters())


def test_template_parameters():
    names = common.template_parameters()
    assert names[0] == 'BucketName'
    assert {'CommandUser', 'ReceiptRuleSetName', 'ReceiptRuleEnabled', 'AlarmEmail'} <= set(names)


# ---------------------------------------------------------------- local vs deployed

DEPLOYED = {'BucketName': 'b', 'ReceiptRuleEnabled': 'false', 'AlarmEmail': ''}


def test_new_stack_uses_local_values():
    assert deploy.plan_parameters({'BucketName': 'b'}, None) == {'BucketName': 'b'}


def test_existing_stack_keeps_deployed_values():
    # Values samconfig.toml doesn't mention stay as deployed.
    assert deploy.plan_parameters({'BucketName': 'b'}, DEPLOYED) == DEPLOYED
    assert deploy.plan_parameters({}, DEPLOYED) == DEPLOYED


def test_local_changes_need_explicit_option():
    local = {'BucketName': 'b', 'ReceiptRuleEnabled': 'true'}
    with pytest.raises(common.Error, match='nothing was deployed'):
        deploy.plan_parameters(local, DEPLOYED)
    assert deploy.plan_parameters(local, DEPLOYED, apply_local_changes=True) == dict(
        DEPLOYED, ReceiptRuleEnabled='true')


def test_parameters_the_template_dropped_are_dropped():
    assert deploy.plan_parameters({}, dict(DEPLOYED, Gone='x'), known=set(DEPLOYED)) == DEPLOYED


def test_pull_keeps_nothing_local_without_explicit_option():
    assert pull_config.merge({}, DEPLOYED) == DEPLOYED
    assert pull_config.merge({'BucketName': 'b'}, DEPLOYED) == DEPLOYED
    with pytest.raises(common.Error, match='nothing was'):
        pull_config.merge({'ReceiptRuleEnabled': 'true'}, DEPLOYED)
    assert pull_config.merge({'ReceiptRuleEnabled': 'true'}, DEPLOYED, overwrite_local=True) == DEPLOYED


def test_override_arguments_quote_values():
    assert deploy.override_arguments({'A': '', 'B': 'x y', 'C': 'a,b', 'D': 'say "hi"'}) == [
        'A=""', 'B="x y"', 'C="a,b"', 'D="say \\"hi\\""']


# ---------------------------------------------------------------- signing keys

@freeze_time('2026-09-14 12:00:00')
def test_script_signs_like_the_function():
    expires = datetime.datetime(2026, 9, 14, 13, 0, 0)
    assert signing_key.sign('test signing key', 'about', 'a@example.com', expires) == \
        control.sign('about', 'a@example.com')
    with freeze_time('2026-09-14 12:30:00'):
        assert control.get_signed_command(
                signing_key.sign('test signing key', 'about', 'a@example.com', expires), 'a@example.com') == 'about'


def test_fingerprint():
    assert signing_key.fingerprint('k') == signing_key.fingerprint(b'k')
    assert signing_key.fingerprint('k') != signing_key.fingerprint('K')
    assert len(signing_key.fingerprint('k')) == 16


class FakeAWS(object):
    def __init__(self, zip_bytes):
        self.zip_bytes = zip_bytes

    def json(self, *args, **kwargs):
        assert args[:2] == ('lambda', 'get-function')
        return {'Code': {'Location': 'https://example.invalid/code.zip'}}


def package(config_source):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as z:
        z.writestr('lambda.py', '')
        if config_source is not None:
            z.writestr('config.py', config_source)
    return buffer.getvalue()


def test_key_from_function(monkeypatch):
    # An old config.py, with a u'' key containing an invalid escape sequence.
    source = (u"# -*- coding: utf-8 -*-\ncommand_user = 'lists'\n"
              u"signing_key = u\"\"\"Old key with \\q and café\"\"\"\n"
              u"from datetime import timedelta\nsigned_validity_interval = timedelta(hours=1)\n").encode('utf-8')
    monkeypatch.setattr(signing_key.urllib.request, 'urlopen', lambda url: io.BytesIO(package(source)))
    assert signing_key.key_from_function(FakeAWS(None), 'LambdaMLM') == u'Old key with \\q and café'


def test_key_from_function_without_config(monkeypatch):
    monkeypatch.setattr(signing_key.urllib.request, 'urlopen', lambda url: io.BytesIO(package(None)))
    with pytest.raises(common.Error, match='no config.py'):
        signing_key.key_from_function(FakeAWS(None), 'LambdaMLM')


class FailingAWS(object):
    def __init__(self, stderr):
        self.stderr = stderr

    def json(self, *args, **kwargs):
        raise common.Error('aws {} failed: {}'.format(' '.join(args[:2]), self.stderr))


def test_describe_stack_missing():
    aws = FailingAWS('An error occurred (ValidationError) when calling the DescribeStacks '
                     'operation: Stack with id LambdaMLM does not exist')
    assert common.describe_stack(aws, 'LambdaMLM') is None


def test_describe_stack_other_failure():
    aws = FailingAWS("Your session has expired. Please reauthenticate using 'aws login'.")
    with pytest.raises(common.Error, match='session has expired'):
        common.describe_stack(aws, 'LambdaMLM')


# ---------------------------------------------------------------- import

def test_import_template():
    template = json.loads(import_bucket.import_template('old-bucket'))
    assert template['Resources'] == {
        'MailBucket': {
            'Type': 'AWS::S3::Bucket',
            'DeletionPolicy': 'Retain',
            'UpdateReplacePolicy': 'Retain',
            'Properties': {'BucketName': 'old-bucket'},
        },
    }


POLICY = {'Version': '2012-10-17', 'Statement': [{'Effect': 'Allow', 'Principal': {'Service': 'ses.amazonaws.com'},
                                                   'Action': 's3:PutObject', 'Resource': 'arn:aws:s3:::old-bucket/*'}]}


def test_import_template_with_existing_policy():
    template = json.loads(import_bucket.import_template('old-bucket', POLICY))
    assert template['Resources']['MailBucketPolicy'] == {
        'Type': 'AWS::S3::BucketPolicy',
        'DeletionPolicy': 'Retain',
        'Properties': {'Bucket': 'old-bucket', 'PolicyDocument': POLICY},
    }


def test_resources_to_import():
    ids = lambda rs: [r['LogicalResourceId'] for r in rs]
    assert ids(import_bucket.resources_to_import('b', None, set())) == ['MailBucket']
    assert ids(import_bucket.resources_to_import('b', POLICY, set())) == ['MailBucket', 'MailBucketPolicy']
    # After a rolled-back deploy, the stack already holds the bucket.
    assert ids(import_bucket.resources_to_import('b', POLICY, {'MailBucket'})) == ['MailBucketPolicy']
    assert import_bucket.resources_to_import('b', POLICY, {'MailBucket', 'MailBucketPolicy'}) == []


# ---------------------------------------------------------------- find-deployments

def test_bucket_from_an_earlier_storing_rule():
    from deploytools import find_deployments
    arn = 'arn:aws:lambda:us-west-2:1:function:LambdaMLM'
    rule_set = {'Metadata': {'Name': 'default-rule-set'}, 'Rules': [
        {'Name': 'other', 'Recipients': ['other.example'], 'Actions': [{'S3Action': {'BucketName': 'wrong'}}]},
        {'Name': 'store-to-s3', 'Enabled': True, 'Actions': [{'S3Action': {'BucketName': 'lists-bucket'}}]},
        {'Name': 'LambdaMLM', 'Enabled': True, 'Actions': [{'LambdaAction': {'FunctionArn': arn}}]},
    ]}

    class AWS(object):
        def json(self, *args, **kwargs):
            return rule_set
    assert find_deployments.rules_invoking(AWS(), arn) == [
        ('default-rule-set', 'LambdaMLM', True, ['(all verified domains)'], 'lists-bucket')]
