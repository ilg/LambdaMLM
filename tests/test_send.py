# -*- coding: utf-8 -*-
"""Posting to a list: policy, header rewriting, moderation and bounces."""

import re
from datetime import timedelta

import pytest
import yaml
from freezegun import freeze_time

import config
import control
import golden
import listobj
from email_utils import ResponseType
from helpers import (HOST, PRODUCTION, member, parse_message, read_bytes,
                     store_list_config, store_production_list, stored_list_config)
from list_exceptions import InsufficientPermissions, ModeratedMessageNotFound, UnknownList
from list_member import MemberFlag

NOW = '2026-09-14 12:00:00'


def raw_message(from_='Alice Sender <alice@example.com>', to='test-list@example.org',
                subject='Hello', headers=(), body='Hello, list.\n',
                message_id='<m1@example.com>'):
    lines = ['From: ' + from_, 'To: ' + to]
    if subject is not None:
        lines.append('Subject: ' + subject)
    if message_id is not None:
        lines.append('Message-ID: ' + message_id)
    lines.extend(headers)
    return ('\n'.join(lines) + '\n\n' + body).encode('utf-8')


def make_list(aws, list_name='test-list', **options):
    options.setdefault('members', [
        member('alice@example.com'),
        member('bob@example.com'),
        member('carol@example.com'),
        ])
    store_list_config(aws, list_name, options)
    return listobj.List('{}@{}'.format(list_name, HOST))


def sent_to(aws):
    return [d for s in aws.ses.sent_raw_emails for d in s['Destinations']]


def sent_message(aws, index=0):
    return parse_message(aws.ses.sent_raw_emails[index]['Data'])


def unfold(value):
    return re.sub(r'\r?\n[ \t]', ' ', value)


# ---------------------------------------------------------------- addresses

def test_list_address_forms(aws):
    l = make_list(aws)
    assert l.verp_address('Bob@Example.com') == 'test-list+Bob=Example.com+bounce@example.org'
    assert l.munged_from('bob@example.com') == 'test-list+bob=example.com+from@example.org'
    assert l.list_address_with_tags('a@b', 'c@d', 'x') == 'test-list+a=b+c=d+x@example.org'


# ---------------------------------------------------------------- recipients

def test_member_post_goes_to_other_members(aws):
    make_list(aws).send(parse_message(raw_message()))
    assert sent_to(aws) == ['bob@example.com', 'carol@example.com']
    assert [s['Source'] for s in aws.ses.sent_raw_emails] == [
        'test-list+bob=example.com+bounce@example.org',
        'test-list+carol=example.com+bounce@example.org',
    ]
    # Every recipient gets the same bytes.
    assert len(set(s['Data'] for s in aws.ses.sent_raw_emails)) == 1


def test_echo_vacation_and_bouncing(aws):
    make_list(aws, members=[
        member('alice@example.com', 'echoPost'),
        member('bob@example.com', 'vacation'),
        member('carol@example.com', 'bouncing'),
        member('dave@example.com'),
        ]).send(parse_message(raw_message()))
    assert sent_to(aws) == ['alice@example.com', 'dave@example.com']


def test_sender_address_is_lowercased_for_lookup(aws):
    make_list(aws).send(parse_message(raw_message(from_='ALICE@EXAMPLE.COM')))
    assert sent_to(aws) == ['bob@example.com', 'carol@example.com']


def test_mixed_case_member_is_a_member(aws):
    l = make_list(aws, members=[member('Alice@Example.com'), member('Bob@Example.com')])
    l.send(parse_message(raw_message(from_='alice@example.com')))
    # Alice doesn't get her own post back; Bob gets it at his stored address.
    assert sent_to(aws) == ['Bob@Example.com']
    assert moderation_keys(aws) == []


# ---------------------------------------------------------------- policy

def test_reject_from_non_members(aws):
    make_list(aws, **{'reject-from-non-members': True}).send(
            parse_message(raw_message(from_='stranger@example.net')))
    assert aws.ses.sent_raw_emails == []
    assert aws.s3.keys(config.s3_bucket) == ['config/example.org/test-list.yaml']


def test_no_post_member(aws):
    make_list(aws, members=[member('alice@example.com', 'noPost'), member('bob@example.com')]).send(
            parse_message(raw_message()))
    assert aws.ses.sent_raw_emails == []


def test_allow_from_non_members(aws):
    make_list(aws, **{'allow-from-non-members': True}).send(
            parse_message(raw_message(from_='stranger@example.net')))
    assert sent_to(aws) == ['alice@example.com', 'bob@example.com', 'carol@example.com']


def test_reject_wins_over_allow(aws):
    make_list(aws, **{'reject-from-non-members': True, 'allow-from-non-members': True}).send(
            parse_message(raw_message(from_='stranger@example.net')))
    assert aws.ses.sent_raw_emails == []


def moderation_keys(aws):
    return [k for k in aws.s3.keys(config.s3_bucket) if k.startswith(config.s3_moderation_prefix)]


@pytest.mark.parametrize('options, from_, members', [
    ({}, 'stranger@example.net', None),
    ({}, 'alice@example.com', [member('alice@example.com', 'modPost')]),
    ({'moderated': True}, 'alice@example.com', [member('alice@example.com')]),
    ({'moderated': True}, 'stranger@example.net', None),
    ({'moderated': True, 'allow-from-non-members': True}, 'stranger@example.net', None),
    ])
def test_moderated(aws, options, from_, members):
    options['members'] = (members or []) + [member('mod@example.com', 'moderator')]
    make_list(aws, **options).send(parse_message(raw_message(from_=from_)))
    assert moderation_keys(aws) == ['moderation/example.org/test-list/<m1@example.com>']
    # Only the moderator hears about it.
    assert sent_to(aws) == ['mod@example.com']


def test_moderated_list_preapproved_member(aws):
    make_list(aws, moderated=True,
              members=[member('alice@example.com', 'preapprove'), member('bob@example.com')]).send(
            parse_message(raw_message()))
    assert sent_to(aws) == ['bob@example.com']


def test_no_post_wins_over_mod_post(aws):
    make_list(aws, members=[member('alice@example.com', 'noPost', 'modPost')]).send(
            parse_message(raw_message()))
    assert aws.ses.sent_raw_emails == []
    assert moderation_keys(aws) == []


def test_mod_approved_skips_policy(aws):
    make_list(aws, **{'reject-from-non-members': True}).send(
            parse_message(raw_message(from_='stranger@example.net')), mod_approved=True)
    assert sent_to(aws) == ['alice@example.com', 'bob@example.com', 'carol@example.com']


# ---------------------------------------------------------------- headers

def test_rewritten_headers(aws):
    make_list(aws, name='Test List').send(parse_message(raw_message(headers=[
        'DKIM-Signature: v=1; d=example.com; b=abc',
        'Return-Path: <alice@example.com>',
        'Sender: someone@example.com',
        ])))
    msg = sent_message(aws)
    assert unfold(msg['From']) == '"Alice Sender (via Test List)" <test-list+alice=example.com+from@example.org>'
    assert msg['Sender'] == 'Test List <test-list@example.org>'
    assert msg['Reply-to'] == 'Alice Sender <alice@example.com>'
    assert msg['X-Original-From'] == 'Alice Sender <alice@example.com>'
    assert msg['X-Original-Sender'] == 'someone@example.com'
    assert msg['X-Original-DKIM-Signature'] == 'v=1; d=example.com; b=abc'
    assert msg['X-Original-Return-path'] == '<alice@example.com>'
    assert msg['DKIM-Signature'] is None
    assert msg['Return-path'] is None
    assert msg['Subject'] == 'Hello'
    assert msg['CC'] is None


def test_from_without_display_name(aws):
    make_list(aws).send(parse_message(raw_message(from_='alice@example.com')))
    assert unfold(sent_message(aws)['From']) == \
        '"alice (via test-list@example.org)" <test-list+alice=example.com+from@example.org>'


def test_reply_to_list(aws):
    make_list(aws, name='Test List', **{'reply-to-list': True}).send(parse_message(raw_message()))
    msg = sent_message(aws)
    assert msg['Reply-to'] == 'Test List <test-list@example.org>'
    assert msg.get_all('CC') == ['Alice Sender <alice@example.com>']


def test_reply_to_list_merges_cc(aws):
    make_list(aws, **{'reply-to-list': True}).send(
            parse_message(raw_message(headers=['Cc: dave@example.com,', ' erin@example.com'])))
    msg = sent_message(aws)
    assert [unfold(v) for v in msg.get_all('CC')] == \
        ['dave@example.com, erin@example.com, Alice Sender <alice@example.com>']
    assert unfold(msg['X-Original-CC']) == 'dave@example.com, erin@example.com'


def test_non_ascii_sender_name(aws):
    from sestools import msg_get_header
    make_list(aws, name='Test List', **{'allow-from-non-members': True}).send(parse_message(raw_message(
            from_='=?utf-8?q?Jos=C3=A9?= <jose@example.net>')))
    assert msg_get_header(sent_message(aws), 'From') == \
        u'Jos\u00e9 (via Test List) <test-list+jose=example.net+from@example.org>'


def test_reply_to_list_non_ascii_sender(aws):
    make_list(aws, **{'reply-to-list': True, 'allow-from-non-members': True}).send(parse_message(raw_message(
            from_='=?utf-8?q?Jos=C3=A9?= <jose@example.net>', headers=['Cc: dave@example.com'])))
    from sestools import msg_get_header
    assert msg_get_header(sent_message(aws), 'CC') == u'dave@example.com, Jos\u00e9 <jose@example.net>'


def test_subject_tag(aws):
    make_list(aws, **{'subject-tag': 'Tag'}).send(parse_message(raw_message(subject='Re: Hello')))
    assert sent_message(aws)['Subject'] == '[Tag] Re: Hello'
    assert sent_message(aws)['X-Original-Subject'] == 'Re: Hello'


def test_subject_tag_already_present(aws):
    make_list(aws, **{'subject-tag': 'Tag'}).send(parse_message(raw_message(subject='Re: [Tag] Hello')))
    assert sent_message(aws)['Subject'] == 'Re: [Tag] Hello'
    assert sent_message(aws)['X-Original-Subject'] is None


def test_subjectless_post_with_subject_tag(aws):
    make_list(aws, **{'subject-tag': 'Tag'}).send(parse_message(raw_message(subject=None)))
    assert sent_message(aws)['Subject'] == '[Tag] '
    assert sent_message(aws)['X-Original-Subject'] is None


def test_subjectless_post_without_subject_tag(aws):
    make_list(aws).send(parse_message(raw_message(subject=None)))
    assert sent_message(aws)['Subject'] is None


def test_from_without_at_sign(aws):
    make_list(aws, **{'allow-from-non-members': True}).send(
            parse_message(raw_message(from_='postmaster')))
    assert sent_to(aws) == ['alice@example.com', 'bob@example.com', 'carol@example.com']
    assert unfold(sent_message(aws)['From']) == \
        '"postmaster (via test-list@example.org)" <test-list+postmaster+from@example.org>'


EIGHT_BIT_BODY = (b'From: Alice Sender <alice@example.com>\n'
                  b'To: test-list@example.org\n'
                  b'Subject: 8-bit body\n'
                  b'Message-ID: <m8@example.com>\n'
                  b'MIME-Version: 1.0\n'
                  b'Content-Type: text/plain\n'
                  b'Content-Transfer-Encoding: 8bit\n'
                  b'\n'
                  b'Caf\xc3\xa9 and na\xefve bytes, undeclared.\n')


def test_eight_bit_from_header(aws):
    from sestools import msg_get_header
    raw = EIGHT_BIT_BODY.replace(b'Alice Sender', b'Al\xc3\xafce Sender')
    make_list(aws).send(parse_message(raw))
    msg = sent_message(aws)
    assert msg_get_header(msg, 'From') == \
        u'Al\u00efce Sender (via test-list@example.org) <test-list+alice=example.com+from@example.org>'
    # The sender's original header goes out as it came in.
    assert b'X-Original-From: Al\xc3\xafce Sender <alice@example.com>' in aws.ses.sent_raw_emails[0]['Data']


# ---------------------------------------------------------------- golden sends

def record_sends(aws, name):
    """Compare every distinct message body sent, and the envelopes, with golden files."""
    datas = []
    envelopes = []
    for s in aws.ses.sent_raw_emails:
        if s['Data'] not in datas:
            datas.append(s['Data'])
        envelopes.append({'source': s['Source'], 'destinations': s['Destinations'],
                          'data': datas.index(s['Data'])})
    for i, data in enumerate(datas):
        golden.check_bytes('sends/{}-{}.eml'.format(name, i), data)
    golden.check_json('sends/{}.json'.format(name), envelopes)


@pytest.mark.parametrize('list_name, fixture, name', [
    ('alpha-list', 'moderation/mod-01-related-utf8qp.eml', 'alpha-mod-01'),
    ('bravo-roster', 'incoming/incoming-02-list-post-pdf.eml', 'bravo-incoming-02'),
    ('delta', 'incoming/incoming-04-list-post-mixedcase-sender.eml', 'delta-incoming-04'),
    ])
def test_production_sends(aws, list_name, fixture, name):
    for n in ('alpha-list', 'bravo-roster', 'charlie-sub-list', 'delta'):
        store_production_list(aws, n)
    l = listobj.List('{}@{}'.format(list_name, HOST))
    l.send(parse_message(read_bytes(PRODUCTION, fixture)), mod_approved=True)
    record_sends(aws, name)


def test_eight_bit_body_send(aws):
    make_list(aws).send(parse_message(EIGHT_BIT_BODY))
    assert b'Caf\xc3\xa9 and na\xefve' in aws.ses.sent_raw_emails[0]['Data']
    record_sends(aws, 'eight-bit-body')


# ---------------------------------------------------------------- cc-lists

def test_cc_lists(aws):
    make_list(aws, 'other', members=[member('dave@example.com'), member('alice@example.com')])
    make_list(aws, **{'cc-lists': ['other@example.org', 'not a list', 'nosuch-but-valid@bad_host']}).send(
            parse_message(raw_message()))
    # The cc-list is sent to first, then this list, each rewriting its own copy.
    assert sent_to(aws) == ['dave@example.com', 'bob@example.com', 'carol@example.com']
    assert unfold(sent_message(aws, 0)['From']).startswith('"Alice Sender (via other@example.org)"')
    assert unfold(sent_message(aws, 1)['From']).startswith('"Alice Sender (via test-list@example.org)"')
    assert sent_message(aws, 1)['X-Original-From'] == 'Alice Sender <alice@example.com>'


def test_cc_list_that_does_not_exist(aws):
    make_list(aws, **{'cc-lists': ['nosuch@example.org']}).send(parse_message(raw_message()))
    assert sent_to(aws) == ['bob@example.com', 'carol@example.com']


def test_mutual_cc_lists(aws):
    make_list(aws, 'other', members=[member('dave@example.com')], **{'cc-lists': ['test-list@example.org']})
    make_list(aws, 'third', members=[member('erin@example.com')], **{'cc-lists': ['other@example.org']})
    make_list(aws, **{'cc-lists': ['other@example.org', 'third@example.org']})
    listobj.List('test-list@example.org').send(parse_message(raw_message()))
    # test-list -> other (which would cc test-list again), and test-list ->
    # third -> other.  Only lists already in the chain are skipped.
    assert sent_to(aws) == ['dave@example.com', 'dave@example.com', 'erin@example.com',
                            'bob@example.com', 'carol@example.com']


# ---------------------------------------------------------------- lists_for_addresses

def test_lists_for_addresses(aws):
    make_list(aws)
    lists = list(listobj.List.lists_for_addresses(
            ['not-an-address', 'Test-List@example.org', 'tag+ged@example.org']))
    assert [l.address for l in lists] == ['test-list@example.org']


def test_lists_for_addresses_none(aws):
    assert list(listobj.List.lists_for_addresses(None)) == []


def test_lists_for_addresses_skips_unknown_lists(aws):
    make_list(aws)
    lists = list(listobj.List.lists_for_addresses(['nosuch@example.org', 'test-list@example.org']))
    assert [l.address for l in lists] == ['test-list@example.org']


# ---------------------------------------------------------------- moderation

FLAT_RULE = {'Rules': [{'ID': 'mod', 'Prefix': 'moderation/', 'Status': 'Enabled',
                        'Expiration': {'Days': 5}}]}
FILTER_RULE = {'Rules': [{'ID': 'mod', 'Filter': {'Prefix': 'moderation/'}, 'Status': 'Enabled',
                          'Expiration': {'Days': 5}}]}


def moderated_list(aws, **options):
    options.setdefault('members', [
        member('mod1@example.com', 'moderator'),
        member('mod2@example.com', 'moderator', 'admin'),
        member('alice@example.com'),
        ])
    return make_list(aws, moderated=True, **options)


@freeze_time(NOW)
def test_moderation_notice(aws):
    aws.s3.lifecycle[config.s3_bucket] = FLAT_RULE
    raw = raw_message(message_id='<id:with:colons@example.com>')
    moderated_list(aws).send(parse_message(raw))
    key = 'moderation/example.org/test-list/<id_with_colons@example.com>'
    assert moderation_keys(aws) == [key]
    assert aws.s3.body(config.s3_bucket, key) == parse_message(raw).as_bytes(policy=listobj.SEND_POLICY)
    notices = aws.ses.sent_raw_emails
    assert [(n['Source'], n['Destinations']) for n in notices] == [
        ('lambda@example.org', ['mod1@example.com']),
        ('lambda@example.org', ['mod2@example.com']),
    ]
    for notice, moderator in zip(notices, ['mod1@example.com', 'mod2@example.com']):
        msg = parse_message(notice['Data'])
        approve = control.sign('list test-list@example.org mod approve "<id_with_colons@example.com>"',
                               moderator, timedelta(days=5))
        reject = control.sign('list test-list@example.org mod reject "<id_with_colons@example.com>"',
                              moderator, timedelta(days=5))
        assert unfold(msg['Subject']) == 'Message to test-list@example.org needs approval: ' + approve
        assert msg['From'] == 'lambda@example.org'
        assert msg['To'] == moderator
        text, forwarded = msg.get_payload()
        # Notices are sent with CRLF line endings.
        assert text.get_payload(decode=True).decode('utf-8').replace('\r\n', '\n') == (
            'The included message needs moderator approval to be posted to test-list@example.org.\n'
            '\n'
            'To approve this message, reply to this email or send an email to lambda@example.org with subject:\n'
            '\n'
            '        {}\n'
            '\n'
            'To reject this message, send an email to lambda@example.org with subject:\n'
            '\n'
            '        {}\n'
            '\n'
            'If no action has been taken in 5 days, the message will be automatically rejected.'
        ).format(approve, reject)
        assert forwarded.get_content_type() == 'message/rfc822'
        assert forwarded.get_payload(0)['Message-ID'] == '<id:with:colons@example.com>'


@freeze_time(NOW)
def test_moderation_without_matching_rule_defaults_to_three_days(aws):
    aws.s3.lifecycle[config.s3_bucket] = {'Rules': [
        {'ID': 'x', 'Prefix': 'other/', 'Status': 'Enabled', 'Expiration': {'Days': 9}}]}
    moderated_list(aws).send(parse_message(raw_message()))
    assert b'automatically rejected' in aws.ses.sent_raw_emails[0]['Data']
    assert b'in 3 days' in aws.ses.sent_raw_emails[0]['Data']


@pytest.mark.parametrize('lifecycle, days', [
    (FLAT_RULE, 5),
    (FILTER_RULE, 5),
    ({'Rules': [{'ID': 'm', 'Filter': {'And': {'Prefix': 'moderation/', 'Tags': []}},
                 'Status': 'Enabled', 'Expiration': {'Days': 7}}]}, 7),
    # Disabled rules, rules without an expiry in days, and other prefixes are ignored.
    ({'Rules': [{'ID': 'm', 'Prefix': 'moderation/', 'Status': 'Disabled', 'Expiration': {'Days': 7}}]}, 3),
    ({'Rules': [{'ID': 'm', 'Filter': {'Prefix': 'moderation/'}, 'Status': 'Enabled',
                 'NoncurrentVersionExpiration': {'NoncurrentDays': 7}}]}, 3),
    ({'Rules': [{'ID': 'm', 'Filter': {}, 'Status': 'Enabled', 'Expiration': {'Days': 7}}]}, 3),
    (None, 3),
    ])
def test_moderation_expiration_days(aws, lifecycle, days):
    if lifecycle is not None:
        aws.s3.lifecycle[config.s3_bucket] = lifecycle
    moderated_list(aws).send(parse_message(raw_message()))
    assert len(aws.ses.sent_raw_emails) == 2
    assert 'in {} days'.format(days).encode('ascii') in aws.ses.sent_raw_emails[0]['Data']


def test_moderation_notice_uses_command_user(aws, monkeypatch):
    monkeypatch.setattr(config, 'command_user', 'lists')
    aws.s3.lifecycle[config.s3_bucket] = FLAT_RULE
    moderated_list(aws).send(parse_message(raw_message()))
    assert aws.ses.sent_raw_emails[0]['Source'] == 'lists@example.org'


def test_moderation_requires_message_id(aws):
    with pytest.raises(ValueError):
        moderated_list(aws).send(parse_message(raw_message(message_id=None)))


def test_moderation_key_for_folded_message_id(aws):
    # Python 2 kept the leading space from a folded Message-ID header in the
    # key.  Python 3's parser strips it; see test_mod_approve_production_held_message
    # for a key with the space.
    raw = raw_message(message_id=None, headers=['Message-ID:', ' <folded@example.com>'])
    moderated_list(aws).send(parse_message(raw))
    assert moderation_keys(aws) == ['moderation/example.org/test-list/<folded@example.com>']


def store_held(aws, key_suffix='<m1@example.com>', raw=None):
    key = 'moderation/example.org/test-list/' + key_suffix
    aws.s3.put(config.s3_bucket, key, raw or raw_message(from_='stranger@example.net'))
    return key


def test_mod_approve(aws):
    key = store_held(aws)
    moderated_list(aws).user_mod_approve('mod1@example.com', '<m1@example.com>')
    assert sent_to(aws) == ['mod1@example.com', 'mod2@example.com', 'alice@example.com']
    assert key not in aws.s3.keys(config.s3_bucket)


def test_mod_approve_production_held_message(aws):
    store_production_list(aws, 'charlie-sub-list')
    data = read_bytes(PRODUCTION, 'moderation', 'mod-02-encodedwords-base64.eml')
    msg_id = parse_message(data)['Message-ID']
    # This message's key has a leading space (see the fixtures README).
    key = 'moderation/example.org/charlie-sub-list/ ' + msg_id
    aws.s3.put(config.s3_bucket, key, data)
    l = listobj.List('charlie-sub-list@example.org')
    moderator = l.moderator_addresses[0]
    l.user_mod_approve(moderator, ' ' + msg_id)
    assert aws.ses.sent_raw_emails
    assert key not in aws.s3.keys(config.s3_bucket)


def test_mod_approve_not_moderator(aws):
    store_held(aws)
    with pytest.raises(InsufficientPermissions):
        moderated_list(aws).user_mod_approve('alice@example.com', '<m1@example.com>')


def test_mod_approve_missing(aws):
    with pytest.raises(ModeratedMessageNotFound):
        moderated_list(aws).user_mod_approve('mod1@example.com', '<nosuch@example.com>')


def test_mod_reject(aws):
    key = store_held(aws)
    moderated_list(aws).user_mod_reject('mod1@example.com', '<m1@example.com>')
    assert aws.ses.sent_raw_emails == []
    assert key not in aws.s3.keys(config.s3_bucket)


def test_mod_reject_missing(aws):
    with pytest.raises(ModeratedMessageNotFound):
        moderated_list(aws).user_mod_reject('mod1@example.com', '<nosuch@example.com>')


# ---------------------------------------------------------------- bounces

BOUNCE = read_bytes(PRODUCTION, '..', 'bounces', 'synthetic', 'ses-permanent.eml')


def bounce_list(aws, **options):
    options.setdefault('members', [member('member@example.com'), member('other@example.com')])
    store_list_config(aws, 'alpha-list', options)


@freeze_time(NOW)
def test_handle_bounce(aws):
    bounce_list(aws)
    listobj.List.handle_bounce_to('alpha-list+member=example.com+bounce@example.org', parse_message(BOUNCE))
    saved = stored_list_config(aws, 'alpha-list')
    golden.check_bytes('bounce-saved/alpha-list.yaml', saved)
    members = yaml.safe_load(saved)['members']
    assert list(members[0].bounces.values()) == [ResponseType.hard]
    assert MemberFlag.bouncing not in members[0].flags


@freeze_time(NOW)
def test_handle_bounce_over_threshold(aws):
    bounce_list(aws, **{'bounce-score-threshold': 0.5})
    listobj.List.handle_bounce_to('alpha-list+member=example.com+bounce@example.org', parse_message(BOUNCE))
    members = yaml.safe_load(stored_list_config(aws, 'alpha-list'))['members']
    assert MemberFlag.bouncing in members[0].flags


@freeze_time(NOW)
def test_handle_bounce_threshold_is_exclusive(aws):
    bounce_list(aws, **{'bounce-score-threshold': 1.0})
    listobj.List.handle_bounce_to('alpha-list+member=example.com+bounce@example.org', parse_message(BOUNCE))
    members = yaml.safe_load(stored_list_config(aws, 'alpha-list'))['members']
    assert MemberFlag.bouncing not in members[0].flags


def test_handle_bounce_no_matching_member(aws):
    bounce_list(aws)
    before = stored_list_config(aws, 'alpha-list')
    listobj.List.handle_bounce_to('alpha-list+nobody=example.com+bounce@example.org', parse_message(BOUNCE))
    assert stored_list_config(aws, 'alpha-list') == before


def test_handle_bounce_verp_match_ignores_case(aws):
    bounce_list(aws, members=[member('Member@Example.com')])
    before = stored_list_config(aws, 'alpha-list')
    listobj.List.handle_bounce_to('alpha-list+member=example.com+bounce@example.org', parse_message(BOUNCE))
    assert stored_list_config(aws, 'alpha-list') != before


@pytest.mark.parametrize('address, error', [
    ('no-at-sign', ValueError),
    ('alpha-list@example.org', ValueError),
    ('nosuch+x=y+bounce@example.org', UnknownList),
    ])
def test_handle_bounce_bad_addresses(aws, address, error):
    bounce_list(aws)
    with pytest.raises(error):
        listobj.List.handle_bounce_to(address, parse_message(BOUNCE))


@pytest.mark.parametrize('from_, members', [
    ('stranger@example.net', None),
    ('alice@example.com', [member('alice@example.com', 'modPost'), member('mod1@example.com', 'moderator')]),
    ])
def test_moderation_paths_with_lifecycle_rule(aws, from_, members):
    aws.s3.lifecycle[config.s3_bucket] = FLAT_RULE
    options = {}
    if members is not None:
        options['members'] = members
    else:
        options['members'] = [member('mod1@example.com', 'moderator'), member('alice@example.com')]
    make_list(aws, **options).send(parse_message(raw_message(from_=from_)))
    assert [s['Destinations'] for s in aws.ses.sent_raw_emails] == [['mod1@example.com']]
    assert moderation_keys(aws) == ['moderation/example.org/test-list/<m1@example.com>']
