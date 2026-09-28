"""The Lambda entry point, end to end, and the SES/email helpers it uses."""

import pytest
import yaml
from botocore.exceptions import ClientError
from freezegun import freeze_time

import settings
import sestools
import signing
from helpers import (FIXTURES, member, parse_message, read_bytes, ses_event,
                     store_incoming, incoming_key, store_list_config,
                     stored_list_config)

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
    return aws.s3.keys(settings.s3_bucket)


# ---------------------------------------------------------------- sestools

def test_msg_get_header():
    msg = parse_message(b'Subject: =?utf-8?q?Caf=C3=A9?= time\nFrom: a@example.com\n\n')
    assert sestools.msg_get_header(msg, 'subject') == 'Café time'
    assert sestools.msg_get_header(msg, 'from') == 'a@example.com'
    assert sestools.msg_get_header(msg, 'reply-to') is None


def test_msg_get_header_raw_eight_bit():
    # Undeclared 8-bit header bytes are read as UTF-8...
    msg = parse_message(b'From: Jos\xc3\xa9 <j@example.com>\n\n')
    assert sestools.msg_get_header(msg, 'from') == 'José <j@example.com>'
    # ...or as Latin-1 if they aren't valid UTF-8.
    msg = parse_message(b'From: Jos\xe9 <j@example.com>\n\n')
    assert sestools.msg_get_header(msg, 'from') == 'José <j@example.com>'


@pytest.mark.parametrize('headers, expected', [
    (b'Reply-To: r@example.com\nFrom: f@example.com\nSender: s@example.com\n', 'r@example.com'),
    (b'From: f@example.com\nSender: s@example.com\n', 'f@example.com'),
    (b'Sender: s@example.com\n', 's@example.com'),
    (b'Subject: x\n', None),
    ])
def test_msg_get_response_address(headers, expected):
    assert sestools.msg_get_response_address(parse_message(headers + b'\n')) == expected


def test_event_recipients():
    event = ses_event('id', recipients=['a@example.org', 'b@example.org'],
                      destination=['b@example.org', 'c@example.net'])
    assert sestools.event_recipients(event) == set(['a@example.org', 'b@example.org'])


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


def test_list_post_call_order(aws, lambda_handler):
    # The incoming message is read first and deleted last, only once the post
    # has been handled.  The keys are spelled out: they're part of the S3 layout.
    make_list(aws)
    store_incoming(aws, 'id1', POST)
    lambda_handler(ses_event('id1', ['test-list@example.org']), None)
    assert aws.log == [
        ('s3', 'get_object', 'incoming/id1'),
        ('s3', 'get_object', 'config/example.org/test-list.yaml'),
        ('ses', 'send_raw_email', 'bob@example.com'),
        ('s3', 'delete_object', 'incoming/id1'),
        ]


def test_incoming_access_denied_is_raised(aws, lambda_handler):
    store_incoming(aws, 'id1', POST)
    aws.s3.deny(settings.s3_bucket, incoming_key('id1'))
    with pytest.raises(ClientError):
        lambda_handler(ses_event('id1', ['test-list@example.org']), None)


def two_lists(aws):
    make_list(aws)
    make_list(aws, 'other', members=[
        member('alice@example.com'), member('bob@example.com'), member('carol@example.com')])
    store_incoming(aws, 'id1', POST)
    return ses_event('id1', ['test-list@example.org', 'other@example.org'])


def test_post_to_two_lists(aws, lambda_handler):
    lambda_handler(two_lists(aws), None)
    # Bob is on both lists and gets two copies.
    assert sorted(d for s in aws.ses.sent_raw_emails for d in s['Destinations']) == \
        ['bob@example.com', 'bob@example.com', 'carol@example.com']
    # Each list rewrote its own copy of the original message.
    for s in aws.ses.sent_raw_emails:
        assert parse_message(s['Data'])['X-Original-From'] == 'Alice Sender <alice@example.com>'


@freeze_time('2026-09-14 12:00:00')
def test_command(aws, lambda_handler):
    store_incoming(aws, 'id1', b'From: a@example.com\nTo: lambda@example.org\nSubject: about\n\n')
    lambda_handler(ses_event('id1', ['lambda@example.org']), None)
    assert aws.ses.sent_emails[0]['Message']['Subject']['Data'] == \
        'Re: ' + signing.sign('about', 'a@example.com')
    assert incoming_key('id1') not in keys(aws)


@freeze_time('2026-09-14 12:00:00')
def test_command_to_other_command_user(aws, lambda_handler, monkeypatch):
    # Settings are read when they're used, so the command address follows them.
    monkeypatch.setattr(settings, 'command_user', 'lists')
    store_incoming(aws, 'id1', b'From: a@example.com\nTo: lists@example.org\nSubject: about\n\n')
    lambda_handler(ses_event('id1', ['lists@example.org']), None)
    assert aws.ses.sent_emails[0]['Message']['Subject']['Data'] == \
        'Re: ' + signing.sign('about', 'a@example.com')


def test_command_with_other_recipient_is_not_a_command(aws, lambda_handler):
    make_list(aws)
    store_incoming(aws, 'id1', POST.replace(b'To: test-list@example.org', b'To: lambda@example.org'))
    # It's handled as a list post; lambda@ isn't a list, so it's skipped.
    lambda_handler(ses_event('id1', ['lambda@example.org', 'test-list@example.org']), None)
    assert aws.ses.sent_emails == []
    assert [s['Destinations'] for s in aws.ses.sent_raw_emails] == [['bob@example.com']]


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


def test_mail_to_non_list_address(aws, lambda_handler):
    store_incoming(aws, 'id1', POST.replace(b'test-list@', b'someone@'))
    lambda_handler(ses_event('id1', ['someone@example.org']), None)
    assert aws.ses.sent_raw_emails == []
    assert incoming_key('id1') not in keys(aws)


def test_bcc_to_list_is_delivered(aws, lambda_handler):
    make_list(aws)
    store_incoming(aws, 'id1', POST.replace(b'To: test-list@example.org', b'To: undisclosed-recipients:;'))
    lambda_handler(ses_event('id1', ['test-list@example.org'], destination=[]), None)
    assert [s['Destinations'] for s in aws.ses.sent_raw_emails] == [['bob@example.com']]


def test_bcc_from_non_member_follows_list_policy(aws, lambda_handler):
    # Bcc'd mail is no longer silently dropped, so it's subject to the list's
    # policy for non-members like any other post.
    make_list(aws, **{'allow-from-non-members': True})
    store_incoming(aws, 'id1', POST.replace(b'To: test-list@example.org', b'To: undisclosed-recipients:;')
                   .replace(b'alice@example.com', b'stranger@example.net'))
    lambda_handler(ses_event('id1', ['test-list@example.org'], destination=[]), None)
    assert sorted(d for s in aws.ses.sent_raw_emails for d in s['Destinations']) == \
        ['alice@example.com', 'bob@example.com']


def test_bcc_to_command_address_is_not_a_command(aws, lambda_handler):
    store_incoming(aws, 'id1', b'From: a@example.com\nTo: someone@example.net\nSubject: about\n\n')
    lambda_handler(ses_event('id1', ['lambda@example.org'], destination=['someone@example.net']), None)
    assert aws.ses.sent_emails == []


def test_eight_bit_from(aws, lambda_handler):
    make_list(aws)
    store_incoming(aws, 'id1', POST.replace(b'Alice Sender', b'Al\xc3\xafce Sender'))
    lambda_handler(ses_event('id1', ['test-list@example.org']), None)
    assert [s['Destinations'] for s in aws.ses.sent_raw_emails] == [['bob@example.com']]
    assert incoming_key('id1') not in keys(aws)


def test_non_ses_event_without_action(aws, lambda_handler):
    assert lambda_handler({}, None) == {'StatusCode': 500, 'Message': 'Internal Server Error'}
