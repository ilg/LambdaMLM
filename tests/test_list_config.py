# -*- coding: utf-8 -*-
"""List loading, saving, configuration and membership operations."""

import glob
import json
import os
from datetime import timedelta

import pytest
from freezegun import freeze_time

import control
import golden
import listobj
from email_utils import ResponseType, bounce_defaults
from helpers import (HOST, PRODUCTION, member, read_bytes, store_list_config,
                     store_production_list, stored_list_config)
from list_exceptions import (
        AlreadySubscribed, ClosedSubscription, ClosedUnsubscription,
        InsufficientPermissions, NotSubscribed, UnknownFlag, UnknownList,
        UnknownOption)
from list_member import MemberFlag

PRODUCTION_LISTS = sorted(
        os.path.basename(p)[:-len('.yaml')]
        for p in glob.glob(os.path.join(PRODUCTION, 'lists', HOST, '*.yaml')))
LOADABLE_LISTS = [n for n in PRODUCTION_LISTS if '_' not in n]


def make_list(aws, list_name='test-list', **options):
    store_list_config(aws, list_name, dict(options, members=options.get('members', [])))
    return listobj.List('{}@{}'.format(list_name, HOST))


def members_of(aws, list_name='test-list'):
    import yaml
    return yaml.safe_load(stored_list_config(aws, list_name))['members']


# ---------------------------------------------------------------- loading

def test_load_by_address(aws):
    store_list_config(aws, 'test-list', {'members': []})
    l = listobj.List('Test-List@Example.ORG')
    assert (l.address, l.username, l.host) == ('test-list@example.org', 'test-list', 'example.org')
    assert l._s3_key == 'config/example.org/test-list.yaml'
    assert l._s3_moderation_prefix == 'moderation/example.org/test-list/'


def test_load_by_username_and_host(aws):
    store_list_config(aws, 'test-list', {'members': []})
    l = listobj.List(username='TEST-LIST', host='EXAMPLE.org')
    assert l.address == 'test-list@example.org'


@pytest.mark.parametrize('kwargs, error', [
    ({}, TypeError),
    ({'username': 'x'}, TypeError),
    ({'address': 'no-at-sign'}, ValueError),
    ({'address': 'under_score@example.org'}, ValueError),
    ({'address': 'dot.ted@example.org'}, ValueError),
    ({'address': 'tag+ged@example.org'}, ValueError),
    ({'address': 'list@bad_host.org'}, ValueError),
    ({'address': 'list@-bad.org'}, ValueError),
    ])
def test_invalid_addresses(aws, kwargs, error):
    with pytest.raises(error):
        listobj.List(**kwargs)


def test_unknown_list(aws):
    with pytest.raises(UnknownList):
        listobj.List('nosuch@example.org')


def test_display_address(aws):
    assert make_list(aws, name='Test List').display_address == u'Test List <test-list@example.org>'
    assert make_list(aws, name='other').display_address == u'other <test-list@example.org>'
    store_list_config(aws, 'unnamed', {'members': []})
    assert listobj.List('unnamed@example.org').display_address == 'unnamed@example.org'


def test_bounce_defaults_are_instance_attributes_only(aws):
    # __setattr__ compares the underscored name with the hyphenated property
    # names, so the defaults set in __init__ never reach the stored config.
    l = make_list(aws)
    assert l.bounce_score_threshold == bounce_defaults.bounce_score_threshold
    assert l.bounce_weights == bounce_defaults.bounce_weights
    assert l.bounce_decay_factor == bounce_defaults.bounce_decay_factor
    l._save()
    stored = stored_list_config(aws, 'test-list')
    assert b'bounce' not in stored
    assert l.dict()['bounce-weights'] is None


def test_bounce_settings_from_config_file(aws):
    l = make_list(aws, **{'bounce-score-threshold': 100000, 'bounce-decay-factor': 0.5})
    assert l.bounce_score_threshold == 100000
    assert l.bounce_decay_factor == 0.5


EXPLICIT_WEIGHTS = {ResponseType.hard: 5.0, ResponseType.soft: 0.25,
                    ResponseType.complaint: 3.0, ResponseType.unknown: 0.0}


def test_bounce_weights_from_config_file(aws):
    l = make_list(aws, **{'bounce-weights': EXPLICIT_WEIGHTS})
    assert l.bounce_weights == EXPLICIT_WEIGHTS
    # The API reports them keyed by name.
    assert api_json(l.dict())['bounce-weights'] == {
        'hard': 5.0, 'soft': 0.25, 'complaint': 3.0, 'unknown': 0.0}
    # Saving writes them back as they were.
    l._save()
    assert b"bounce-weights:\n  !bouncekind 'hard': 5.0\n" in stored_list_config(aws, 'test-list')


def test_falsy_bounce_settings_use_the_defaults(aws):
    # A stored value of 0 or {} counts as unset: the defaults apply, but the
    # stored values are what's reported and saved.
    l = make_list(aws, **{'bounce-score-threshold': 0, 'bounce-weights': {}, 'bounce-decay-factor': 0})
    assert l.bounce_score_threshold == bounce_defaults.bounce_score_threshold
    assert l.bounce_weights == bounce_defaults.bounce_weights
    assert l.bounce_decay_factor == bounce_defaults.bounce_decay_factor
    d = l.dict()
    assert (d['bounce-score-threshold'], d['bounce-weights'], d['bounce-decay-factor']) == (0, {}, 0)
    l._save()
    stored = stored_list_config(aws, 'test-list')
    assert b'bounce-score-threshold: 0\n' in stored
    assert b'bounce-weights: {}\n' in stored


def test_config_is_loaded_and_saved_at_the_literal_key(aws):
    l = make_list(aws)
    l._save()
    assert aws.log[-2:] == [
        ('s3', 'get_object', 'config/example.org/test-list.yaml'),
        ('s3', 'put_object', 'config/example.org/test-list.yaml'),
        ]


def test_property_access(aws):
    l = make_list(aws, **{'subject-tag': 'Tag', 'reply-to-list': True})
    assert l.subject_tag == 'Tag'
    assert l.reply_to_list is True
    assert l.moderated is None
    with pytest.raises(AttributeError):
        l.not_a_property


@pytest.mark.parametrize('name', LOADABLE_LISTS)
def test_production_list_round_trip(aws, name):
    # Loading and saving a production list must write exactly these bytes.
    store_production_list(aws, name)
    listobj.List('{}@{}'.format(name, HOST))._save()
    saved = stored_list_config(aws, name)
    golden.check_bytes('saved-lists/{}.yaml'.format(name), saved)


@pytest.mark.parametrize('name', [n for n in LOADABLE_LISTS if n != 'india'])
def test_production_list_round_trip_is_identity(aws, name):
    # Every list the code wrote itself comes back byte for byte.
    store_production_list(aws, name)
    listobj.List('{}@{}'.format(name, HOST))._save()
    assert stored_list_config(aws, name) == read_bytes(PRODUCTION, 'lists', HOST, name + '.yaml')


# ---------------------------------------------------------------- dict / API shape

def api_json(value):
    """Serialize like the Lambda runtime does, with flags sorted for stability."""
    for m in value.get('members') or []:
        m['flags'] = sorted(m['flags'])
    return json.loads(json.dumps(value))


@pytest.mark.parametrize('name', ['alpha-list', 'bravo-roster', 'india'])
def test_production_list_dict(aws, name):
    store_production_list(aws, name)
    d = listobj.List('{}@{}'.format(name, HOST)).dict()
    assert sorted(d) == sorted(listobj.list_properties)
    golden.check_json('list-dicts/{}.json'.format(name), api_json(d))


def test_update_from_dict(aws):
    l = make_list(aws)
    l.update_from_dict({'subject-tag': 'New', 'not-a-property': 1, 'moderated': True})
    stored = stored_list_config(aws, 'test-list')
    assert b'subject-tag: New' in stored
    assert b'moderated: true' in stored
    assert b'not-a-property' not in stored


def test_update_from_dict_rejects_members(aws):
    with pytest.raises(KeyError):
        make_list(aws).update_from_dict({'members': []})


def test_update_from_dict_can_set_protected_cc_lists(aws):
    make_list(aws).update_from_dict({'cc-lists': ['other@example.org']})
    assert b'cc-lists:\n- other@example.org' in stored_list_config(aws, 'test-list')


# ---------------------------------------------------------------- subscription

def admin_list(aws, **options):
    options.setdefault('members', [
        member('admin@example.com', 'admin'),
        member('plain@example.com'),
        ])
    return make_list(aws, **options)


def test_self_subscribe_closed(aws):
    with pytest.raises(ClosedSubscription):
        admin_list(aws).user_subscribe_user('new@example.com', 'new@example.com')


def test_self_subscribe_open(aws):
    admin_list(aws, **{'open-subscription': True}).user_subscribe_user(
            'New Person <New@Example.com>', 'New Person <New@Example.com>')
    added = members_of(aws)[-1]
    # The stored address keeps its case; see test_members.
    assert (added.address, added.name) == ('New@Example.com', 'New Person')


def test_admin_subscribes_other(aws):
    admin_list(aws).user_subscribe_user('admin@example.com', 'new@example.com')
    assert members_of(aws)[-1].address == 'new@example.com'


def test_non_admin_subscribes_other(aws):
    with pytest.raises(InsufficientPermissions):
        admin_list(aws).user_subscribe_user('plain@example.com', 'new@example.com')


def test_subscribe_already_subscribed(aws):
    with pytest.raises(AlreadySubscribed):
        admin_list(aws).user_subscribe_user('admin@example.com', 'plain@example.com')


def test_self_unsubscribe(aws):
    admin_list(aws).user_unsubscribe_user('plain@example.com', 'plain@example.com')
    assert [m.address for m in members_of(aws)] == ['admin@example.com']


def test_self_unsubscribe_closed(aws):
    with pytest.raises(ClosedUnsubscription):
        admin_list(aws, **{'closed-unsubscription': True}).user_unsubscribe_user(
                'plain@example.com', 'plain@example.com')


def test_admin_unsubscribes_other_on_closed_list(aws):
    admin_list(aws, **{'closed-unsubscription': True}).user_unsubscribe_user(
            'admin@example.com', 'plain@example.com')
    assert [m.address for m in members_of(aws)] == ['admin@example.com']


def test_unsubscribe_non_member(aws):
    with pytest.raises(NotSubscribed):
        admin_list(aws).user_unsubscribe_user('x@example.com', 'x@example.com')


# ---------------------------------------------------------------- flags

def test_own_flags_non_admin(aws):
    l = make_list(aws, members=[member('a@example.com', 'echoPost', 'moderator')])
    assert l.user_own_flags('A <a@example.com>') == [
        (MemberFlag.vacation, False), (MemberFlag.echoPost, True)]


def test_own_flags_admin(aws):
    l = make_list(aws, members=[member('a@example.com', 'admin')])
    assert [(f.name, v) for f, v in l.user_own_flags('a@example.com')] == [
        ('modPost', False), ('preapprove', False), ('noPost', False),
        ('moderator', False), ('superAdmin', False), ('admin', True),
        ('vacation', False), ('echoPost', False), ('bouncing', False)]


def test_own_flags_not_subscribed(aws):
    with pytest.raises(NotSubscribed):
        make_list(aws).user_own_flags('a@example.com')


def test_set_own_userlevel_flag(aws):
    l = make_list(aws, members=[member('a@example.com')])
    l.user_set_member_flag_value('a@example.com', 'a@example.com', 'vacation', True)
    assert members_of(aws)[0].flags == set([MemberFlag.vacation])
    l.user_set_member_flag_value('a@example.com', 'a@example.com', 'vacation', False)
    assert members_of(aws)[0].flags == set()
    # Unsetting a flag that isn't set is fine.
    l.user_set_member_flag_value('a@example.com', 'a@example.com', 'vacation', False)


def test_set_own_admin_level_flag(aws):
    with pytest.raises(InsufficientPermissions):
        make_list(aws, members=[member('a@example.com')]).user_set_member_flag_value(
                'a@example.com', 'a@example.com', 'moderator', True)


def test_admin_sets_other_members_flag(aws):
    l = make_list(aws, members=[member('admin@example.com', 'admin'), member('a@example.com')])
    l.user_set_member_flag_value('admin@example.com', 'a@example.com', 'moderator', True)
    assert members_of(aws)[1].flags == set([MemberFlag.moderator])


def test_super_admin_flag_cannot_be_set(aws):
    l = make_list(aws, members=[member('s@example.com', 'admin', 'superAdmin')])
    with pytest.raises(InsufficientPermissions):
        l.user_set_member_flag_value('s@example.com', 's@example.com', 'superAdmin', False)


def test_unknown_flag(aws):
    with pytest.raises(UnknownFlag):
        make_list(aws, members=[member('a@example.com')]).user_set_member_flag_value(
                'a@example.com', 'a@example.com', 'nope', True)


def test_flag_on_non_member(aws):
    l = make_list(aws, members=[member('admin@example.com', 'admin')])
    with pytest.raises(NotSubscribed):
        l.user_set_member_flag_value('admin@example.com', 'x@example.com', 'vacation', True)


# ---------------------------------------------------------------- options

def test_config_values(aws):
    l = admin_list(aws, **{'subject-tag': 'Tag'})
    values = l.user_config_values('admin@example.com')
    assert [o for o, _ in values] == [
        'name', 'subject-tag', 'bounce-score-threshold', 'bounce-weights',
        'bounce-decay-factor', 'reply-to-list', 'open-subscription',
        'closed-unsubscription', 'moderated', 'reject-from-non-members',
        'allow-from-non-members']
    assert dict(values)['subject-tag'] == 'Tag'
    assert dict(values)['bounce-weights'] is None


def test_config_values_non_admin(aws):
    with pytest.raises(InsufficientPermissions):
        admin_list(aws).user_config_values('plain@example.com')


def test_set_config_value(aws):
    admin_list(aws).user_set_config_value('admin@example.com', 'subject-tag', 'New')
    assert b'subject-tag: New' in stored_list_config(aws, 'test-list')


@pytest.mark.parametrize('option', ['members', 'cc-lists', 'nope', 'subject_tag'])
def test_set_config_value_unknown_or_protected(aws, option):
    with pytest.raises(UnknownOption):
        admin_list(aws).user_set_config_value('admin@example.com', option, 'x')


def test_set_config_value_non_admin(aws):
    with pytest.raises(InsufficientPermissions):
        admin_list(aws).user_set_config_value('plain@example.com', 'subject-tag', 'x')


def test_get_members(aws):
    l = admin_list(aws)
    assert l.user_get_members('admin@example.com') == ['admin@example.com: admin', 'plain@example.com: ']


def test_get_members_non_admin(aws):
    with pytest.raises(InsufficientPermissions):
        admin_list(aws).user_get_members('plain@example.com')


def test_update_member_from_dict(aws):
    l = admin_list(aws)
    l.update_member_from_dict(l.members[1], {'name': 'Plain'})
    assert members_of(aws)[1].name == 'Plain'


# ---------------------------------------------------------------- invitations

NOW = '2026-09-14 12:00:00'


@freeze_time(NOW)
def test_invite_subscribe_member(aws):
    l = admin_list(aws, name='Test List')
    l.invite_subscribe_member('new@example.com')
    (sent,) = aws.ses.sent_emails
    token = control.sign('new@example.com', 'test-list@example.org',
                         validity_duration=timedelta(days=3))
    cmd = 'list test-list@example.org accept_subscription_invitation "{}"'.format(token)
    assert sent == {
        'Source': 'lambda@example.org',
        'Destination': {'ToAddresses': ['new@example.com']},
        'Message': {
            'Subject': {'Data': 'Invitation to join Test List - Fwd: {}'.format(
                control.sign(cmd, 'new@example.com', validity_duration=timedelta(days=3)))},
            'Body': {'Text': {'Data': 'To accept the invitation, reply to this email.  '
                                      'You can leave the body of the reply blank.'}},
        },
    }


@freeze_time(NOW)
def test_invite_uses_address_without_name(aws):
    admin_list(aws).invite_subscribe_member('new@example.com')
    assert 'Invitation to join test-list@example.org - Fwd: list test-list@example.org ' \
           'accept_subscription_invitation "new@example.com ' in \
           aws.ses.sent_emails[0]['Message']['Subject']['Data']


def test_invite_already_subscribed(aws):
    with pytest.raises(AlreadySubscribed):
        admin_list(aws).invite_subscribe_member('plain@example.com')


@freeze_time(NOW)
def test_invite_unsubscribe_member(aws):
    l = admin_list(aws)
    l.invite_unsubscribe_member(l.members[1])
    subject = aws.ses.sent_emails[0]['Message']['Subject']['Data']
    assert subject.startswith('Invitation to leave test-list@example.org - Fwd: '
                              'list test-list@example.org accept_unsubscription_invitation "')


def test_invite_unsubscribe_non_member(aws):
    with pytest.raises(NotSubscribed):
        admin_list(aws).invite_unsubscribe_member(None)


def invitation_token(address):
    with freeze_time(NOW):
        return control.sign(address, 'test-list@example.org', validity_duration=timedelta(days=3))


def test_accept_subscription_invitation(aws):
    token = invitation_token('new@example.com')
    with freeze_time(NOW):
        admin_list(aws).accept_subscription_invitation('New <new@example.com>', token)
    added = members_of(aws)[-1]
    assert (added.address, added.name) == ('new@example.com', 'New')


def test_accept_invitation_from_other_address(aws):
    token = invitation_token('new@example.com')
    with freeze_time(NOW):
        with pytest.raises(control.InvalidSignatureException):
            admin_list(aws).accept_subscription_invitation('other@example.com', token)


def test_accept_invitation_for_mixed_case_address(aws):
    token = invitation_token('New@Example.com')
    with freeze_time(NOW):
        admin_list(aws).accept_subscription_invitation('New@Example.com', token)
    # The member is stored with the address as given.
    assert members_of(aws)[-1].address == 'New@Example.com'


def test_accept_expired_invitation(aws):
    token = invitation_token('new@example.com')
    with freeze_time('2026-09-17 12:00:01'):
        with pytest.raises(control.ExpiredSignatureException):
            admin_list(aws).accept_subscription_invitation('new@example.com', token)


def test_accept_unsubscription_invitation(aws):
    token = invitation_token('plain@example.com')
    with freeze_time(NOW):
        admin_list(aws).accept_unsubscription_invitation('plain@example.com', token)
    assert [m.address for m in members_of(aws)] == ['admin@example.com']
