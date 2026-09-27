# -*- coding: utf-8 -*-
"""The deployment scripts' packaging, config handling and parameters."""

import importlib.util
import json
import os
from importlib.machinery import SourceFileLoader

import pytest
import yaml

from helpers import TESTS_DIR

ROOT = os.path.dirname(TESTS_DIR)


def load_script(name):
    loader = SourceFileLoader(name.replace('-', '_'), os.path.join(ROOT, 'scripts', name))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


deploy = load_script('deploy')
import_bucket = load_script('import-bucket')


def template_parameters():
    class Loader(yaml.SafeLoader):
        pass
    # Accept CloudFormation's short-form tags (!Ref, !Sub, ...).
    Loader.add_multi_constructor('!', lambda loader, suffix, node: None)
    with open(os.path.join(ROOT, 'template.yaml')) as f:
        return yaml.load(f, Loader=Loader)['Parameters']


def write(path, text=''):
    if not os.path.isdir(os.path.dirname(path)):
        os.makedirs(os.path.dirname(path))
    with open(path, 'w') as f:
        f.write(text)


def test_stage_packages_code_and_config_only(tmp_path):
    source = tmp_path / 'lambda'
    for name in ['lambda.py', 'config.py', 'config.example.py', 'config.prod.py', 'requirements.txt',
                 '.lambda.py.swp', 'x.pyc', '__pycache__/y.pyc', 'api/actions.py', 'api/.actions.py.swp',
                 'api/config.py.bak~', 'templates/notify_moderators.jinja2', 'control/config.py']:
        write(str(source / name))
    destination = tmp_path / 'build'
    deploy.stage(str(source), str(destination))
    staged = sorted(os.path.relpath(os.path.join(d, f), str(destination))
                    for d, _, files in os.walk(str(destination)) for f in files)
    assert staged == ['api/actions.py', 'config.py', 'control/config.py', 'lambda.py',
                      'requirements.txt', 'templates/notify_moderators.jinja2']


def test_stage_real_function(tmp_path):
    destination = tmp_path / 'build'
    deploy.stage(destination=str(destination))
    for name in ('lambda.py', 'listobj.py', 'lamson_bounce.py', 'requirements.txt',
                 'templates/notify_moderators.jinja2', 'control/list_commands.py', 'api/actions.py'):
        assert (destination / name).exists(), name
    assert not (destination / 'config.example.py').exists()


def example_config():
    return deploy.load_config(deploy.CONFIG_EXAMPLE)


def test_check_config_rejects_example_values():
    example = example_config()
    with pytest.raises(deploy.ConfigError, match='signing_key'):
        deploy.check_config(dict(example), example)
    with pytest.raises(deploy.ConfigError, match='s3_bucket'):
        deploy.check_config(dict(example, signing_key='mine'), example)
    with pytest.raises(deploy.ConfigError, match='lambda_region'):
        deploy.check_config(dict(example, signing_key='mine', s3_bucket='b', lambda_region=None), example)
    deploy.check_config(dict(example, signing_key='mine', s3_bucket='my-bucket'), example)


def test_load_config_missing(tmp_path):
    with pytest.raises(deploy.ConfigError, match='config.example.py'):
        deploy.load_config(str(tmp_path / 'config.py'))


def test_load_config_reports_warnings(tmp_path, capsys):
    path = tmp_path / 'config.py'
    # An invalid escape sequence, like the one in the production signing key.
    path.write_text(u"signing_key = u'a\\qb'\n")
    assert deploy.load_config(str(path))['signing_key'] == u'a\\qb'
    assert 'invalid escape sequence' in capsys.readouterr().err


def test_parameter_overrides_from_example():
    config = dict(example_config(), s3_bucket='my-bucket')
    assert deploy.parameter_overrides(config) == [
        'BucketName=my-bucket',
        'IncomingPrefix=incoming/',
        'ModerationExpirationDays=3',
        'ModerationPrefix=moderation/',
        'ReceiptRuleEnabled=true',
        'ReceiptRuleSetName=default-rule-set',
    ]


def test_parameter_overrides_for_existing_deployment():
    # A config.py from before these settings existed.
    config = dict(s3_bucket='old-bucket', receipt_rule_set='default-rule-set',
                  receipt_rule_enabled=False, receipt_rule_recipients=['example.org', 'example.net'],
                  alarm_email='ops@example.org')
    assert deploy.parameter_overrides(config) == [
        'AlarmEmail=ops@example.org',
        'BucketName=old-bucket',
        'ReceiptRuleEnabled=false',
        'ReceiptRuleRecipients=example.org,example.net',
        'ReceiptRuleSetName=default-rule-set',
    ]
    assert deploy.stack_name(config) == 'LambdaMLM'


def test_parameter_overrides_match_template():
    config = dict(example_config(), s3_bucket='b', receipt_rule_recipients=['x'], alarm_email='a@x',
                  incoming_expiration_days=7)
    names = [p.split('=', 1)[0] for p in deploy.parameter_overrides(config)]
    assert set(names) <= set(template_parameters())


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
