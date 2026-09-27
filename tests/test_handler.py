# -*- coding: utf-8 -*-
"""The Lambda entry point, end to end, and the SES/email helpers it uses."""

import pytest
import yaml
from botocore.exceptions import ClientError
from freezegun import freeze_time

import config
import control
import sestools
from helpers import (FIXTURES, member, parse_message, read_bytes, ses_event,
                     store_incoming, incoming_key, store_list_config,
                     stored_list_config)
from list_exceptions import UnknownList

POST = (b'From: Alice Sender <alice@example.com>\n'
        b'To: test-list@example.org\n'
        b'Subject: Hello\n'
        b'Message-ID: <m1@example.com>\n'
        b'\n'
        b'Hello, list.\n')


def make_list(aws, list_name='test-list', **options):
    options.setdefault('members', [member('alice@example.com'), member('bob@example.com')])
    store_list_config(aws, list_name, options)


def keys(aws):
    return aws.s3.keys(config.s3_bucket)


# ---------------------------------------------------------------- sestools

def test_msg_get_header():
    msg = parse_message(b'Subject: =?utf-8?q?Caf=C3=A9?= time\nFrom: a@example.com\n\n')
    assert sestools.msg_get_header(msg, 'subject') == u'Café time'
    assert sestools.msg_get_header(msg, 'from') == u'a@example.com'
    assert sestools.msg_get_header(msg, 'reply-to') is None


def test_msg_get_header_raw_eight_bit_crashes():
    msg = parse_message(b'From: Jos\xc3\xa9 <j@example.com>\n\n')
    with pytest.raises(UnicodeDecodeError):
        sestools.msg_get_header(msg, 'from')


@pytest.mark.xfail(strict=True, raises=UnicodeDecodeError,
                   reason='Python 2 decodes raw 8-bit headers as ASCII.')
def test_msg_get_header_raw_eight_bit():
    msg = parse_message(b'From: Jos\xc3\xa9 <j@example.com>\n\n')
    assert sestools.msg_get_header(msg, 'from') == u'José <j@example.com>'


@pytest.mark.parametrize('headers, expected', [
    (b'Reply-To: r@example.com\nFrom: f@example.com\nSender: s@example.com\n', 'r@example.com'),
    (b'From: f@example.com\nSender: s@example.com\n', 'f@example.com'),
    (b'Sender: s@example.com\n', 's@example.com'),
    (b'Subject: x\n', None),
    ])
def test_msg_get_response_address(headers, expected):
    assert sestools.msg_get_response_address(parse_message(headers + b'\n')) == expected


def test_recipient_destination_overlap():
    event = ses_event('id', recipients=['a@example.org', 'b@example.org'],
                      destination=['b@example.org', 'c@example.net'])
    assert sestools.recipient_destination_overlap(event) == set(['b@example.org'])


COMMAND = parse_message(b'From: a@example.com\nTo: Lists <lambda@example.org>\nSubject: about\n\n')


@pytest.mark.parametrize('recipients, destination, msg, expected', [
    (['lambda@example.org'], ['lambda@example.org'], COMMAND, 'lambda@example.org'),
    (['lambda@example.org', 'x@example.org'], ['lambda@example.org'], COMMAND, False),
    (['lambda@example.org'], ['lambda@example.org', 'x@example.org'], COMMAND, False),
    (['x@example.org'], ['lambda@example.org'], COMMAND, False),
    (['lambda@example.org'], ['x@example.org'], COMMAND, False),
    (['lambda@example.org'], ['lambda@example.org'],
     parse_message(b'From: a@example.com\nTo: x@example.org\n\n'), False),
    # The checks are prefix matches on "lambda@", in any domain.
    (['lambda@other.example'], ['lambda@example.org'], COMMAND, 'lambda@example.org'),
    ])
def test_event_msg_is_to_command(recipients, destination, msg, expected):
    event = ses_event('id', recipients=recipients, destination=destination)
    assert sestools.event_msg_is_to_command(event, msg) == expected


def test_email_message_for_event(aws):
    store_incoming(aws, 'id1', POST)
    with sestools.email_message_for_event(ses_event('id1', ['test-list@example.org'])) as msg:
        assert msg['Subject'] == 'Hello'
        assert incoming_key('id1') in keys(aws)
    assert incoming_key('id1') not in keys(aws)


def test_email_message_for_event_deletes_on_error(aws):
    store_incoming(aws, 'id1', POST)
    with pytest.raises(RuntimeError):
        with sestools.email_message_for_event(ses_event('id1', ['test-list@example.org'])):
            raise RuntimeError('handling failed')
    assert incoming_key('id1') not in keys(aws)


@pytest.mark.xfail(strict=True, reason='Step 3: keep incoming mail when handling fails.')
def test_email_message_for_event_keeps_message_on_error(aws):
    store_incoming(aws, 'id1', POST)
    with pytest.raises(RuntimeError):
        with sestools.email_message_for_event(ses_event('id1', ['test-list@example.org'])):
            raise RuntimeError('handling failed')
    assert incoming_key('id1') in keys(aws)


def test_email_message_for_event_delete_failure(aws, monkeypatch):
    store_incoming(aws, 'id1', POST)

    def fail(**kwargs):
        raise ClientError({'Error': {'Code': 'AccessDenied', 'Message': 'no'}}, 'DeleteObject')
    monkeypatch.setattr(aws.s3, 'delete_object', fail)
    with pytest.raises(ClientError):
        with sestools.email_message_for_event(ses_event('id1', ['test-list@example.org'])):
            pass


def test_email_message_for_event_missing(aws):
    with pytest.raises(ClientError):
        with sestools.email_message_for_event(ses_event('nosuch', ['test-list@example.org'])):
            pass


# ---------------------------------------------------------------- lambda_handler

def test_api_event(aws, lambda_handler):
    make_list(aws)
    result = lambda_handler({'Action': 'GetList', 'ListAddress': 'test-list@example.org'}, None)
    assert result['StatusCode'] == 200


def test_list_post(aws, lambda_handler):
    make_list(aws)
    store_incoming(aws, 'id1', POST)
    assert lambda_handler(ses_event('id1', ['test-list@example.org']), None) is None
    assert [s['Destinations'] for s in aws.ses.sent_raw_emails] == [['bob@example.com']]
    assert incoming_key('id1') not in keys(aws)


def two_lists(aws):
    make_list(aws)
    make_list(aws, 'other', members=[
        member('alice@example.com'), member('bob@example.com'), member('carol@example.com')])
    store_incoming(aws, 'id1', POST)
    return ses_event('id1', ['test-list@example.org', 'other@example.org'])


def test_post_to_two_lists_second_list_sees_rewritten_message(aws, lambda_handler):
    # The first list rewrites the shared message in place (including From),
    # so the second list sees a non-member sender and moderates the post.
    # Which list goes first depends on set iteration order.
    with pytest.raises(ClientError) as e:
        lambda_handler(two_lists(aws), None)
    assert e.value.response['Error']['Code'] == 'NoSuchLifecycleConfiguration'
    sent = [d for s in aws.ses.sent_raw_emails for d in s['Destinations']]
    assert sent in (['bob@example.com'], ['bob@example.com', 'carol@example.com'])


@pytest.mark.xfail(strict=True, raises=ClientError,
                   reason='Step 3: each list should get its own copy of the incoming message.')
def test_post_to_two_lists(aws, lambda_handler):
    lambda_handler(two_lists(aws), None)
    # Bob is on both lists and gets two copies.
    assert sorted(d for s in aws.ses.sent_raw_emails for d in s['Destinations']) == \
        ['bob@example.com', 'bob@example.com', 'carol@example.com']


@freeze_time('2026-09-14 12:00:00')
def test_command(aws, lambda_handler):
    store_incoming(aws, 'id1', b'From: a@example.com\nTo: lambda@example.org\nSubject: about\n\n')
    lambda_handler(ses_event('id1', ['lambda@example.org']), None)
    assert aws.ses.sent_emails[0]['Message']['Subject']['Data'] == \
        'Re: ' + control.sign('about', 'a@example.com')
    assert incoming_key('id1') not in keys(aws)


def test_command_with_other_recipient_is_not_a_command(aws, lambda_handler):
    make_list(aws)
    store_incoming(aws, 'id1', POST.replace(b'To: test-list@example.org', b'To: lambda@example.org'))
    # lambda@ isn't a list, so treating the message as a list post fails.
    with pytest.raises(UnknownList):
        lambda_handler(ses_event('id1', ['lambda@example.org', 'test-list@example.org']), None)
    assert aws.ses.sent_emails == []


@freeze_time('2026-09-14 12:00:00')
def test_bounce(aws, lambda_handler):
    store_list_config(aws, 'alpha-list', {'members': [member('member@example.com')]})
    store_incoming(aws, 'id1', read_bytes(FIXTURES, 'bounces', 'synthetic', 'ses-permanent.eml'))
    lambda_handler(ses_event('id1', ['alpha-list+member=example.com+bounce@example.org'],
                             destination=['alpha-list+member=example.com+bounce@example.org']), None)
    (m,) = yaml.safe_load(stored_list_config(aws, 'alpha-list'))['members']
    assert len(m.bounces) == 1
    assert aws.ses.sent_raw_emails == []
    assert incoming_key('id1') not in keys(aws)


def test_mail_to_non_list_address_crashes(aws, lambda_handler):
    store_incoming(aws, 'id1', POST.replace(b'test-list@', b'someone@'))
    with pytest.raises(UnknownList):
        lambda_handler(ses_event('id1', ['someone@example.org']), None)
    # The message was deleted anyway.
    assert incoming_key('id1') not in keys(aws)


@pytest.mark.xfail(strict=True, raises=UnknownList,
                   reason='Step 3: mail to an address that isn\'t a list should be ignored.')
def test_mail_to_non_list_address(aws, lambda_handler):
    store_incoming(aws, 'id1', POST.replace(b'test-list@', b'someone@'))
    lambda_handler(ses_event('id1', ['someone@example.org']), None)


def test_bcc_to_list_is_dropped(aws, lambda_handler):
    make_list(aws)
    store_incoming(aws, 'id1', POST.replace(b'To: test-list@example.org', b'To: undisclosed-recipients:;'))
    lambda_handler(ses_event('id1', ['test-list@example.org'], destination=[]), None)
    assert aws.ses.sent_raw_emails == []


@pytest.mark.xfail(strict=True, reason='Step 3: BCC\'d list mail should be delivered.')
def test_bcc_to_list_is_delivered(aws, lambda_handler):
    make_list(aws)
    store_incoming(aws, 'id1', POST.replace(b'To: test-list@example.org', b'To: undisclosed-recipients:;'))
    lambda_handler(ses_event('id1', ['test-list@example.org'], destination=[]), None)
    assert aws.ses.sent_raw_emails


def test_eight_bit_from_crashes_before_routing(aws, lambda_handler):
    make_list(aws)
    store_incoming(aws, 'id1', POST.replace(b'Alice Sender', b'Al\xc3\xafce Sender'))
    with pytest.raises(UnicodeDecodeError):
        lambda_handler(ses_event('id1', ['test-list@example.org']), None)
    assert incoming_key('id1') not in keys(aws)


def test_non_ses_event_without_action(aws, lambda_handler):
    assert lambda_handler({}, None) == {'StatusCode': 500, 'Message': 'Internal Server Error'}
