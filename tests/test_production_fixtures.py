# -*- coding: utf-8 -*-
"""Checks that the production fixtures are usable by the current code."""

import email
import glob
import os

import pytest

import config
import listobj

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'production')
LIST_FILES = sorted(glob.glob(os.path.join(FIXTURES, 'lists', 'example.org', '*.yaml')))
MESSAGE_FILES = sorted(
        glob.glob(os.path.join(FIXTURES, 'moderation', '*.eml'))
        + glob.glob(os.path.join(FIXTURES, 'incoming', '*.eml')))


def list_name(path):
    return os.path.basename(path)[:-len('.yaml')]


def store_list(aws, path):
    with open(path, 'rb') as f:
        aws.s3.put(
                config.s3_bucket,
                '{}example.org/{}.yaml'.format(config.s3_configuration_prefix, list_name(path)),
                f.read())


def test_fixtures_exist():
    assert len(LIST_FILES) == 13
    assert len(MESSAGE_FILES) == 7


@pytest.mark.parametrize('path', LIST_FILES, ids=list_name)
def test_list_config_loads(aws, path):
    store_list(aws, path)
    address = '{}@example.org'.format(list_name(path))
    if '_' in list_name(path):
        # The name fails name_regex, so this list can never be loaded.
        with pytest.raises(ValueError):
            listobj.List(address)
        return
    with open(path, 'rb') as f:
        member_count = f.read().count(b'- !Member')
    assert len(listobj.List(address).members) == member_count


@pytest.mark.parametrize('path', MESSAGE_FILES, ids=os.path.basename)
def test_message_parses(path):
    with open(path, 'rb') as f:
        data = f.read()
    # message_from_bytes only exists on Python 3.
    parse = getattr(email, 'message_from_bytes', email.message_from_string)
    msg = parse(data)
    assert msg.get_content_type()
