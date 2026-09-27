# -*- coding: utf-8 -*-
"""Email commands: the signing round trip and each command's output."""

from datetime import timedelta

import pytest
import yaml
from freezegun import freeze_time

import config
import control
from control import commands
from helpers import (HOST, member, parse_message, store_list_config,
                     stored_list_config)
from list_member import MemberFlag

NOW = '2026-09-14 12:00:00'
COMMAND_ADDRESS = 'lambda@example.org'


def make_list(aws, list_name='test-list', **options):
    options.setdefault('members', [
        member('admin@example.com', 'admin'),
        member('mod@example.com', 'moderator'),
        member('plain@example.com'),
        ])
    store_list_config(aws, list_name, options)


def members_of(aws, list_name='test-list'):
    return yaml.safe_load(stored_list_config(aws, list_name))['members']


def run(user, cmd):
    return commands.run(user=user, cmd=cmd)


# ---------------------------------------------------------------- handle_command

def command_message(subject, from_='Plain <plain@example.com>', headers=()):
    lines = ['From: ' + from_, 'To: ' + COMMAND_ADDRESS]
    if subject is not None:
        lines.append('Subject: ' + subject)
    lines.extend(headers)
    return parse_message(('\n'.join(lines) + '\n\nbody\n').encode('utf-8'))


@freeze_time(NOW)
def test_unsigned_command_gets_signed_reply(aws):
    control.handle_command(COMMAND_ADDRESS, command_message('list test-list@example.org subscribe'))
    (sent,) = aws.ses.sent_emails
    signed = control.sign('list test-list@example.org subscribe', 'Plain <plain@example.com>')
    assert sent == {
        'Source': COMMAND_ADDRESS,
        'Destination': {'ToAddresses': ['Plain <plain@example.com>']},
        'Message': {
            'Subject': {'Data': 'Re: ' + signed},
            'Body': {'Text': {'Data': 'To confirm and execute the command, please reply to this email.'}},
        },
    }


@freeze_time(NOW)
def test_reply_prefixes_are_stripped(aws):
    control.handle_command(COMMAND_ADDRESS, command_message('Re: Fwd: about'))
    assert aws.ses.sent_emails[0]['Message']['Subject']['Data'].startswith('Re: about ')


@freeze_time(NOW)
def test_signed_command_is_run(aws):
    make_list(aws, **{'open-subscription': True})
    signed = control.sign('list test-list@example.org subscribe', 'New <new@example.com>')
    control.handle_command(COMMAND_ADDRESS, command_message('Re: ' + signed, from_='New <new@example.com>'))
    (sent,) = aws.ses.sent_emails
    assert sent['Destination'] == {'ToAddresses': ['New <new@example.com>']}
    assert sent['Message']['Subject']['Data'] == 'Re: ' + signed
    assert sent['Message']['Body']['Text']['Data'] == (
        'Output of "list test-list@example.org subscribe":\n\n'
        'New <new@example.com> has been subscribed to test-list@example.org.\n')
    assert members_of(aws)[-1].address == 'new@example.com'


def test_expired_command_is_ignored(aws):
    with freeze_time(NOW):
        signed = control.sign('about', 'plain@example.com')
    with freeze_time('2026-09-14 13:00:01'):
        control.handle_command(COMMAND_ADDRESS, command_message(signed, from_='plain@example.com'))
    assert aws.ses.sent_emails == []


@freeze_time(NOW)
def test_command_signed_for_someone_else_is_ignored(aws):
    signed = control.sign('about', 'other@example.com')
    control.handle_command(COMMAND_ADDRESS, command_message(signed, from_='plain@example.com'))
    assert aws.ses.sent_emails == []


@freeze_time(NOW)
def test_reply_to_is_preferred(aws):
    control.handle_command(COMMAND_ADDRESS, command_message(
            'about', headers=['Reply-To: other@example.com']))
    assert aws.ses.sent_emails[0]['Destination'] == {'ToAddresses': ['other@example.com']}


@pytest.mark.parametrize('value', ['auto-replied', 'auto-generated', 'Auto-Replied'])
def test_auto_submitted_is_ignored(aws, value):
    control.handle_command(COMMAND_ADDRESS, command_message('about', headers=['Auto-Submitted: ' + value]))
    assert aws.ses.sent_emails == []


def test_auto_submitted_no_is_processed(aws):
    control.handle_command(COMMAND_ADDRESS, command_message('about', headers=['Auto-Submitted: No']))
    assert len(aws.ses.sent_emails) == 1


def test_subjectless_command_crashes(aws):
    with pytest.raises(AttributeError):
        control.handle_command(COMMAND_ADDRESS, command_message(None))


@pytest.mark.xfail(strict=True, raises=AttributeError,
                   reason='Step 3: command mail with no subject should be ignored.')
def test_subjectless_command_is_ignored(aws):
    control.handle_command(COMMAND_ADDRESS, command_message(None))
    assert aws.ses.sent_emails == []


# ---------------------------------------------------------------- run: basics

def test_about():
    assert run('a@example.com', 'about') == 'This is the about command.\n'


def test_echo():
    assert run('a@example.com', 'echo one "two three"') == \
        'This is the echo command.  You are a@example.com.\none two three\n'
    assert run('a@example.com', 'echo') == \
        'This is the echo command.  You are a@example.com.\n[no parameters]\n'


def test_command_names():
    # Invitation emails embed these names, so they must never change.  Each
    # command names itself explicitly so a Click upgrade can't rename it.
    from control import list_commands
    assert sorted(commands.command.commands) == ['about', 'echo', 'list']
    assert sorted(list_commands.list_command.commands) == [
        'accept_subscription_invitation', 'accept_unsubscription_invitation',
        'members', 'mod', 'set', 'setflag', 'subscribe', 'unsetflag', 'unsubscribe']
    assert sorted(list_commands.moderate.commands) == ['approve', 'reject']


def test_unknown_command():
    assert run('a@example.com', 'nope') == 'Internal error.'


def test_hyphenated_command_name():
    # Click 6 keeps underscores in command names; Click 7 would use hyphens.
    assert run('a@example.com', 'list test-list@example.org accept-subscription-invitation x') == \
        'Internal error.'


def test_invalid_list_address(aws):
    assert run('a@example.com', 'list not-an-address subscribe') == \
        'not-an-address is not a valid list address.\n'


def test_unknown_list_is_internal_error(aws):
    assert run('a@example.com', 'list nosuch@example.org subscribe') == 'Internal error.'


@pytest.mark.xfail(strict=True, reason='Step 3: require_list should catch UnknownList.')
def test_unknown_list(aws):
    assert run('a@example.com', 'list nosuch@example.org subscribe') == \
        'nosuch@example.org is not a valid list address.\n'


def test_non_ascii_arguments_crash():
    with pytest.raises(UnicodeEncodeError):
        run(u'a@example.com', u'echo José')


@pytest.mark.xfail(strict=True, raises=UnicodeEncodeError,
                   reason='Python 2 shlex can\'t split non-ASCII text.')
def test_non_ascii_arguments():
    assert u'José' in run(u'a@example.com', u'echo José')


# ---------------------------------------------------------------- run: subscription

def test_subscribe_closed(aws):
    make_list(aws)
    # ClosedSubscription is reported as an invalid list address.
    assert run('new@example.com', 'list test-list@example.org subscribe') == \
        'test-list@example.org is not a valid list address.\n'


def test_subscribe_open(aws):
    make_list(aws, **{'open-subscription': True})
    assert run('new@example.com', 'list test-list@example.org subscribe') == \
        'new@example.com has been subscribed to test-list@example.org.\n'


def test_admin_subscribes_other(aws):
    make_list(aws)
    assert run('admin@example.com', 'list test-list@example.org subscribe new@example.com') == \
        'new@example.com has been subscribed to test-list@example.org.\n'


def test_subscribe_insufficient(aws):
    make_list(aws)
    assert run('plain@example.com', 'list test-list@example.org subscribe new@example.com') == \
        'You do not have sufficient permissions to subscribe new@example.com to test-list@example.org..\n'


def test_subscribe_already(aws):
    make_list(aws, **{'open-subscription': True})
    assert run('plain@example.com', 'list test-list@example.org subscribe') == \
        'plain@example.com is already subscribed to test-list@example.org.\n'


def test_unsubscribe(aws):
    make_list(aws)
    assert run('plain@example.com', 'list test-list@example.org unsubscribe') == \
        'plain@example.com has been unsubscribed from test-list@example.org.\n'


def test_unsubscribe_not_subscribed(aws):
    make_list(aws)
    assert run('x@example.com', 'list test-list@example.org unsubscribe') == \
        'You are not subscribed to test-list@example.org.\n'
    assert run('admin@example.com', 'list test-list@example.org unsubscribe x@example.com') == \
        'x@example.com is not subscribed to test-list@example.org.\n'


def test_unsubscribe_closed(aws):
    make_list(aws, **{'closed-unsubscription': True})
    assert run('plain@example.com', 'list test-list@example.org unsubscribe') == (
        'test-list@example.org does not allow members to unsubscribe themselves.  '
        'Please contact the list administrator to be removed from the list.\n')


def test_unsubscribe_insufficient(aws):
    make_list(aws)
    assert run('plain@example.com', 'list test-list@example.org unsubscribe admin@example.com') == \
        'You do not have sufficient permissions to unsubscribe admin@example.com from test-list@example.org..\n'


# ---------------------------------------------------------------- run: invitations

def invitation(address, verb='subscription'):
    with freeze_time(NOW):
        token = control.sign(address, 'test-list@example.org', validity_duration=timedelta(days=3))
    return 'list test-list@example.org accept_{}_invitation "{}"'.format(verb, token)


@freeze_time(NOW)
def test_accept_subscription_invitation(aws):
    make_list(aws)
    assert run('New <new@example.com>', invitation('new@example.com')) == \
        'You are now subscribed to test-list@example.org.\n'


@freeze_time(NOW)
def test_accept_invitation_wrong_address(aws):
    make_list(aws)
    assert run('other@example.com', invitation('new@example.com')) == \
        'The invitation is not valid for other@example.com.\n'


def test_accept_invitation_expired(aws):
    make_list(aws)
    cmd = invitation('new@example.com')
    with freeze_time('2026-09-18 12:00:00'):
        assert run('new@example.com', cmd) == 'The invitation has expired.\n'


@freeze_time(NOW)
def test_accept_invitation_already_subscribed(aws):
    make_list(aws)
    assert run('plain@example.com', invitation('plain@example.com')) == \
        'You are already subscribed to test-list@example.org.\n'


@freeze_time(NOW)
def test_accept_unsubscription_invitation(aws):
    make_list(aws)
    assert run('plain@example.com', invitation('plain@example.com', 'unsubscription')) == \
        'You are no longer subscribed to test-list@example.org.\n'


@freeze_time(NOW)
def test_accept_unsubscription_invitation_not_subscribed(aws):
    make_list(aws)
    assert run('x@example.com', invitation('x@example.com', 'unsubscription')) == \
        'You are not subscribed to test-list@example.org.\n'


# ---------------------------------------------------------------- run: flags

def test_setflag_lists_flags(aws):
    make_list(aws)
    assert run('plain@example.com', 'list test-list@example.org setflag') == \
        'Available flags:\nvacation: False\nechoPost: False\n'


def test_setflag_lists_flags_not_subscribed(aws):
    make_list(aws)
    assert run('x@example.com', 'list test-list@example.org setflag') == \
        'Available flags:\nYou are not subscribed to test-list@example.org.\n'


def test_setflag_and_unsetflag(aws):
    make_list(aws)
    assert run('plain@example.com', 'list test-list@example.org setflag vacation') == \
        'Set flag vacation on plain@example.com.\n'
    assert members_of(aws)[2].flags == set([MemberFlag.vacation])
    assert run('plain@example.com', 'list test-list@example.org unsetflag vacation') == \
        'Unset flag vacation on plain@example.com.\n'
    assert members_of(aws)[2].flags == set()


def test_setflag_on_other(aws):
    make_list(aws)
    assert run('admin@example.com', 'list test-list@example.org setflag moderator plain@example.com') == \
        'Set flag moderator on plain@example.com.\n'


def test_setflag_insufficient(aws):
    make_list(aws)
    assert run('plain@example.com', 'list test-list@example.org setflag moderator') == \
        'You do not have sufficient permissions to change the moderator flag on plain@example.com..\n'


def test_setflag_unknown(aws):
    make_list(aws)
    assert run('plain@example.com', 'list test-list@example.org setflag nope') == 'nope is not a valid flag.\n'


def test_setflag_not_subscribed(aws):
    make_list(aws)
    assert run('admin@example.com', 'list test-list@example.org setflag vacation x@example.com') == \
        'x@example.com is not subscribed to test-list@example.org.\n'


# ---------------------------------------------------------------- run: options

def test_set_lists_options(aws):
    make_list(aws, **{'subject-tag': 'Tag'})
    assert run('admin@example.com', 'list test-list@example.org set') == (
        'Configuration for test-list@example.org:\n'
        'name: None\n'
        'subject-tag: Tag\n'
        'bounce-score-threshold: None\n'
        'bounce-weights: None\n'
        'bounce-decay-factor: None\n'
        'reply-to-list: None\n'
        'open-subscription: None\n'
        'closed-unsubscription: None\n'
        'moderated: None\n'
        'reject-from-non-members: None\n'
        'allow-from-non-members: None\n')


def test_set_lists_options_insufficient(aws):
    make_list(aws)
    assert run('plain@example.com', 'list test-list@example.org set') == (
        'Configuration for test-list@example.org:\n'
        'You do not have sufficient permissions to view options on test-list@example.org..\n')


@pytest.mark.parametrize('args, output, stored', [
    ('moderated --true', 'Set moderated to True', b'moderated: true'),
    ('moderated --false', 'Set moderated to False', b'moderated: false'),
    # --true and --false share a destination whose default under Click 6 is
    # False, not None, so every other form stores False.
    ('subject-tag New', 'Set subject-tag to False', b'subject-tag: false'),
    ('bounce-score-threshold --int 5', 'Set bounce-score-threshold to False', b'bounce-score-threshold: false'),
    ('moderated true', 'Set moderated to False', b'moderated: false'),
    ])
def test_set_option(aws, args, output, stored):
    make_list(aws)
    assert run('admin@example.com', 'list test-list@example.org set ' + args) == \
        output + ' on test-list@example.org.\n'
    assert stored in stored_list_config(aws, 'test-list')


@pytest.mark.xfail(strict=True, reason='Step 3: set should store the value it was given.')
@pytest.mark.parametrize('args, stored', [
    ('subject-tag New', b'subject-tag: New'),
    ('bounce-score-threshold --int 5', b'bounce-score-threshold: 5'),
    ])
def test_set_option_value(aws, args, stored):
    make_list(aws)
    run('admin@example.com', 'list test-list@example.org set ' + args)
    assert stored in stored_list_config(aws, 'test-list')


def test_set_unknown_option(aws):
    make_list(aws)
    assert run('admin@example.com', 'list test-list@example.org set cc-lists x') == \
        'cc-lists is not a valid configuration option.\n'


def test_set_option_insufficient(aws):
    make_list(aws)
    assert run('plain@example.com', 'list test-list@example.org set moderated --true') == \
        'You do not have sufficient permissions to change moderated on test-list@example.org..\n'


def test_members(aws):
    make_list(aws)
    assert run('admin@example.com', 'list test-list@example.org members') == (
        'Members of test-list@example.org:\n'
        'admin@example.com: admin\n'
        'mod@example.com: moderator\n'
        'plain@example.com: \n')


def test_members_insufficient(aws):
    make_list(aws)
    assert run('plain@example.com', 'list test-list@example.org members') == (
        'Members of test-list@example.org:\n'
        'You do not have sufficient permissions to view the members of test-list@example.org..\n')


# ---------------------------------------------------------------- run: moderation

def store_held(aws):
    aws.s3.put(config.s3_bucket, 'moderation/example.org/test-list/<m1@example.com>',
               b'From: stranger@example.net\nTo: test-list@example.org\nSubject: Hi\n'
               b'Message-ID: <m1@example.com>\n\nHello.\n')


def test_mod_approve(aws):
    make_list(aws)
    store_held(aws)
    assert run('mod@example.com', 'list test-list@example.org mod approve "<m1@example.com>"') == \
        'Post approved.\n'
    assert len(aws.ses.sent_raw_emails) == 3


def test_mod_reject(aws):
    make_list(aws)
    store_held(aws)
    assert run('mod@example.com', 'list test-list@example.org mod reject "<m1@example.com>"') == \
        'Post rejected.\n'


def test_mod_not_found(aws):
    make_list(aws)
    for action in ('approve', 'reject'):
        assert run('mod@example.com', 'list test-list@example.org mod {} "<x@example.com>"'.format(action)) == \
            'Message not found.  It may already have been acted on.\n'


def test_mod_insufficient(aws):
    make_list(aws)
    store_held(aws)
    assert run('plain@example.com', 'list test-list@example.org mod approve "<m1@example.com>"') == \
        'You do not have sufficient permissions to moderate messages on test-list@example.org..\n'


def test_command_without_response_address_is_ignored(aws):
    msg = parse_message(b'To: lambda@example.org\nSubject: about\n\n')
    control.handle_command(COMMAND_ADDRESS, msg)
    assert aws.ses.sent_emails == []


def test_mod_reject_insufficient(aws):
    make_list(aws)
    store_held(aws)
    assert run('plain@example.com', 'list test-list@example.org mod reject "<m1@example.com>"') == \
        'You do not have sufficient permissions to moderate messages on test-list@example.org..\n'
