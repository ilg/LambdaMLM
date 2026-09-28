"""The direct-invoke API used by the web app."""

import json

import pytest
import yaml
from freezegun import freeze_time

import signing
from api import handle_api
from helpers import member, store_list_config, stored_list_config


def make_list(aws, **options):
    options.setdefault('members', [
        member('admin@example.com', 'admin'),
        member('Plain@Example.com'),
        ])
    options.setdefault('name', 'Test List')
    store_list_config(aws, 'test-list', options)


def call(**event):
    result = handle_api(event)
    # The Lambda runtime JSON-serializes the return value.
    return json.loads(json.dumps(result))


def members_of(aws):
    return yaml.safe_load(stored_list_config(aws, 'test-list'))['members']


def test_unknown_action(aws):
    assert call(Action='Nope') == {'StatusCode': 500, 'Message': 'Internal Server Error'}
    assert call() == {'StatusCode': 500, 'Message': 'Internal Server Error'}


def test_get_list(aws):
    make_list(aws)
    result = call(Action='GetList', ListAddress='test-list@example.org')
    assert result['StatusCode'] == 200
    data = result['Data']
    assert data['name'] == 'Test List'
    assert data['bounce-weights'] is None
    assert data['members'] == [
        {'address': 'admin@example.com', 'name': None, 'flags': ['admin']},
        {'address': 'Plain@Example.com', 'name': None, 'flags': []},
    ]


@pytest.mark.parametrize('address', ['nosuch@example.org', 'not-an-address', None])
def test_get_unknown_list(aws, address):
    assert call(Action='GetList', ListAddress=address) == \
        {'StatusCode': 404, 'Message': 'List {} not found.'.format(address)}


def test_create_list(aws):
    make_list(aws)
    assert call(Action='CreateList', ListAddress='test-list@example.org') == \
        {'StatusCode': 400, 'Message': 'test-list@example.org already exists.'}
    assert call(Action='CreateList', ListAddress='new@example.org') == \
        {'StatusCode': 501, 'Message': 'Not Implemented'}


def test_update_list(aws):
    make_list(aws)
    result = call(Action='UpdateList', ListAddress='test-list@example.org', Data={'subject-tag': 'Tag'})
    assert result['StatusCode'] == 200
    assert result['Data']['subject-tag'] == 'Tag'
    assert b'subject-tag: Tag' in stored_list_config(aws, 'test-list')


def test_update_list_members_rejected(aws):
    make_list(aws)
    assert call(Action='UpdateList', ListAddress='test-list@example.org', Data={'members': []}) == \
        {'StatusCode': 400, 'Message': 'Invalid data.'}


def test_missing_argument(aws):
    make_list(aws)
    result = call(Action='UpdateList', ListAddress='test-list@example.org')
    # The message is the TypeError's text, which differs between Python versions.
    assert result['StatusCode'] == 400
    assert 'update_list()' in result['Message']


def test_missing_argument_debug(aws):
    make_list(aws)
    with pytest.raises(TypeError):
        handle_api({'Action': 'UpdateList', 'ListAddress': 'test-list@example.org', 'Debug': True})


def test_create_member(aws):
    make_list(aws)
    assert call(Action='CreateMember', ListAddress='test-list@example.org',
                MemberAddress='New Person <new@example.com>') == {'StatusCode': 201, 'Data': None}
    added = members_of(aws)[-1]
    assert (added.address, added.name) == ('new@example.com', 'New Person')


def test_create_member_already_subscribed(aws):
    make_list(aws)
    assert call(Action='CreateMember', ListAddress='test-list@example.org',
                MemberAddress='admin@example.com') == \
        {'StatusCode': 400, 'Message': 'admin@example.com is already subscribed.'}


@freeze_time('2026-09-14 12:00:00')
def test_invite_member(aws):
    make_list(aws)
    assert call(Action='InviteMember', ListAddress='test-list@example.org',
                MemberAddress='new@example.com') == {'StatusCode': 204, 'Data': None}
    (sent,) = aws.ses.sent_emails
    assert sent['Destination'] == {'ToAddresses': ['new@example.com']}
    assert sent['Message']['Subject']['Data'].startswith('Invitation to join Test List - Fwd: ')


def test_invite_member_already_subscribed(aws):
    make_list(aws)
    assert call(Action='InviteMember', ListAddress='test-list@example.org',
                MemberAddress='admin@example.com') == \
        {'StatusCode': 400, 'Message': 'admin@example.com is already subscribed.'}


def test_get_member(aws):
    make_list(aws)
    assert call(Action='GetMember', ListAddress='test-list@example.org', MemberAddress='admin@example.com') == \
        {'StatusCode': 200, 'Data': {'address': 'admin@example.com', 'name': None, 'flags': ['admin']}}


def test_get_member_lookup_ignores_case(aws):
    make_list(aws)
    for address in ('plain@example.com', 'Plain@Example.com', 'PLAIN@EXAMPLE.COM'):
        assert call(Action='GetMember', ListAddress='test-list@example.org', MemberAddress=address) == \
            {'StatusCode': 200, 'Data': {'address': 'Plain@Example.com', 'name': None, 'flags': []}}


def test_get_member_unknown_list(aws):
    assert call(Action='GetMember', ListAddress='nosuch@example.org', MemberAddress='a@example.com') == \
        {'StatusCode': 404, 'Message': 'List nosuch@example.org not found.'}


def test_update_member(aws):
    make_list(aws)
    result = call(Action='UpdateMember', ListAddress='test-list@example.org',
                  MemberAddress='admin@example.com', Data={'name': 'Admin', 'flags': ['admin', 'moderator']})
    assert result['StatusCode'] == 200
    assert result['Data']['name'] == 'Admin'
    assert sorted(result['Data']['flags']) == ['admin', 'moderator']
    assert members_of(aws)[0].name == 'Admin'


def test_update_member_bad_flag(aws):
    make_list(aws)
    assert call(Action='UpdateMember', ListAddress='test-list@example.org',
                MemberAddress='admin@example.com', Data={'flags': ['nope']}) == \
        {'StatusCode': 400, 'Message': 'Invalid data.'}


@freeze_time('2026-09-14 12:00:00')
def test_unsubscribe_member(aws):
    make_list(aws)
    assert call(Action='UnsubscribeMember', ListAddress='test-list@example.org',
                MemberAddress='admin@example.com') == {'StatusCode': 204, 'Data': None}
    assert aws.ses.sent_emails[0]['Message']['Subject']['Data'].startswith('Invitation to leave Test List - Fwd: ')
    assert len(members_of(aws)) == 2


def test_delete_member(aws):
    make_list(aws)
    assert call(Action='DeleteMember', ListAddress='test-list@example.org',
                MemberAddress='admin@example.com') == {'StatusCode': 204, 'Data': None}
    assert [m.address for m in members_of(aws)] == ['Plain@Example.com']


def test_delete_unknown_member(aws):
    make_list(aws)
    assert call(Action='DeleteMember', ListAddress='test-list@example.org',
                MemberAddress='x@example.com') == \
        {'StatusCode': 404, 'Message': 'Member x@example.com not found.'}


def test_verify_signed_command(aws):
    with freeze_time('2026-09-14 12:00:00'):
        signed = signing.sign('about', 'admin@example.com')
        assert call(Action='VerifySignedCommand', Subject=signed, Address='admin@example.com') == \
            {'StatusCode': 200, 'Data': {'Result': 'Valid', 'Command': 'about'}}
        assert call(Action='VerifySignedCommand', Subject=signed.replace('about', 'abort'),
                    Address='admin@example.com')['Data'] == {'Result': 'Invalid'}
        assert call(Action='VerifySignedCommand', Subject=signed, Address='other@example.com')['Data'] == \
            {'Result': 'Invalid'}
        assert call(Action='VerifySignedCommand', Subject='about', Address='admin@example.com')['Data'] == \
            {'Result': 'NotSigned'}
    with freeze_time('2026-09-14 13:00:01'):
        assert call(Action='VerifySignedCommand', Subject=signed, Address='admin@example.com')['Data'] == \
            {'Result': 'Expired'}
