# -*- coding: utf-8 -*-
"""Shared helpers for the characterization tests."""

import email
import os

import yaml

import settings

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(TESTS_DIR, 'fixtures')
PRODUCTION = os.path.join(FIXTURES, 'production')
HOST = 'example.org'


def read_bytes(*path):
    with open(os.path.join(*path), 'rb') as f:
        return f.read()


def parse_message(data):
    """Parse raw message bytes the way the code parses stored mail."""
    # message_from_bytes only exists on Python 3.
    parse = getattr(email, 'message_from_bytes', email.message_from_string)
    return parse(data)


def config_key(list_name, host=HOST):
    return '{}{}/{}.yaml'.format(settings.s3_configuration_prefix, host, list_name)


def store_list_config(aws, list_name, data, host=HOST):
    """Store a list config (bytes, or a dict to be dumped as YAML)."""
    if isinstance(data, dict):
        data = yaml.safe_dump(data, default_flow_style=False, allow_unicode=True)
    aws.s3.put(settings.s3_bucket, config_key(list_name, host), data)


def store_production_list(aws, list_name):
    store_list_config(
            aws, list_name,
            read_bytes(PRODUCTION, 'lists', HOST, list_name + '.yaml'))


def stored_list_config(aws, list_name, host=HOST):
    return aws.s3.body(settings.s3_bucket, config_key(list_name, host))


def member(address, *flags, **extra):
    """A member entry for a list config dict, as the code would store it."""
    import list_member
    m = list_member.ListMember(address, *[list_member.MemberFlag[f] for f in flags])
    for k, v in extra.items():
        setattr(m, k, v)
    return m


def ses_event(message_id, recipients, destination=None):
    """An SES receipt event as delivered to the Lambda function."""
    return {
        'Records': [{
            'ses': {
                'mail': {
                    'messageId': message_id,
                    'destination': list(destination if destination is not None else recipients),
                },
                'receipt': {
                    'recipients': list(recipients),
                },
            },
        }],
    }


def store_incoming(aws, message_id, data):
    aws.s3.put(settings.s3_bucket, settings.s3_incoming_email_prefix + message_id, data)


def incoming_key(message_id):
    return settings.s3_incoming_email_prefix + message_id
