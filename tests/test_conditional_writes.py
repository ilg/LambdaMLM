"""Conditional saves of list configs, and what each caller does when one fails.

A save is conditional on the ETag the list was loaded with, so a write that
races another one fails instead of silently overwriting it.  Bounces start
again from a fresh copy of the list; email commands and API calls report the
conflict.
"""

import json

import pytest
import yaml
from botocore.exceptions import ClientError
from freezegun import freeze_time

import listobj
import settings
import storage
from api import handle_api
from bounces import ResponseType
from control import commands
from helpers import FIXTURES, HOST, config_key, member, parse_message, read_bytes, store_list_config, stored_list_config
from list_exceptions import ListChanged, ListNotFound, UnknownList

NOW = '2026-09-14 12:00:00'
KEY = config_key('test-list')
COMMAND_CONFLICT = 'The list changed while your command was running.  Please try again.'
API_CONFLICT = {'StatusCode': 409, 'Message': 'The list changed while this request was running. Try again.'}


def make_list(aws, **options):
    options.setdefault('members', [
        member('admin@example.com', 'admin'),
        member('plain@example.com'),
        ])
    store_list_config(aws, 'test-list', options)


def load():
    return listobj.List('test-list@' + HOST)


def addresses(aws):
    return [m.address for m in yaml.safe_load(stored_list_config(aws, 'test-list'))['members']]


def another_writer_adds(aws, address):
    """Save the list as another invocation would, adding a member."""
    config = yaml.safe_load(stored_list_config(aws, 'test-list'))
    config['members'].append(member(address))
    store_list_config(aws, 'test-list', config)


@pytest.fixture
def racing_writer(aws, monkeypatch):
    """Another writer saves the list right after each of the next `times`
    loads, adding racer1@example.com, racer2@example.com and so on."""
    real_load = storage.load_list_config
    state = {'remaining': 0, 'count': 0}

    def load_list_config(host, username):
        result = real_load(host, username)
        if state['remaining']:
            state['remaining'] -= 1
            state['count'] += 1
            another_writer_adds(aws, 'racer{}@example.com'.format(state['count']))
        return result
    monkeypatch.setattr(storage, 'load_list_config', load_list_config)

    def race(times=1):
        state['remaining'] = times
    return race


# ---------------------------------------------------------------- storage

def test_missing_list_is_list_not_found(aws):
    with pytest.raises(ListNotFound):
        load()
    assert issubclass(ListNotFound, UnknownList)


def test_unreadable_list_is_only_unknown_list(aws):
    # Only S3's not-found means the list doesn't exist.
    make_list(aws)
    aws.s3.deny(settings.s3_bucket, KEY)
    with pytest.raises(UnknownList) as e:
        load()
    assert not isinstance(e.value, ListNotFound)


def test_save_passes_the_etag_as_loaded(aws, monkeypatch):
    # S3 returns ETags in quotes, and they're passed back exactly as returned.
    make_list(aws)
    l = load()
    loaded_etag = aws.s3.etags[(settings.s3_bucket, KEY)]
    assert loaded_etag.startswith('"')
    calls = []
    real_put = aws.s3.put_object
    monkeypatch.setattr(aws.s3, 'put_object', lambda **kwargs: calls.append(kwargs) or real_put(**kwargs))
    l._save()
    assert calls[0]['IfMatch'] == loaded_etag


def test_save_refreshes_the_etag(aws):
    # So saving the same list object twice doesn't conflict with itself.
    make_list(aws)
    l = load()
    l.add_member('one@example.com')
    l.add_member('two@example.com')
    assert l._etag == aws.s3.etags[(settings.s3_bucket, KEY)]
    assert addresses(aws) == ['admin@example.com', 'plain@example.com', 'one@example.com', 'two@example.com']


def test_save_after_another_write_fails(aws):
    make_list(aws)
    l = load()
    another_writer_adds(aws, 'racer@example.com')
    with pytest.raises(ListChanged):
        l.add_member('new@example.com')
    assert addresses(aws) == ['admin@example.com', 'plain@example.com', 'racer@example.com']


@pytest.mark.parametrize('code', ['PreconditionFailed', 'ConditionalRequestConflict'])
def test_conflicts_reported_by_s3_are_list_changed(aws, code):
    make_list(aws)
    l = load()
    aws.s3.fail_puts(settings.s3_bucket, KEY, code)
    with pytest.raises(ListChanged):
        l._save()


def test_save_of_a_deleted_list_is_list_not_found(aws):
    make_list(aws)
    l = load()
    aws.s3.delete_object(Bucket=settings.s3_bucket, Key=KEY)
    with pytest.raises(ListNotFound):
        l._save()
    assert KEY not in aws.s3.keys(settings.s3_bucket)


def test_other_save_errors_pass_through(aws):
    make_list(aws)
    l = load()
    aws.s3.deny(settings.s3_bucket, KEY)
    with pytest.raises(ClientError) as e:
        l._save()
    assert e.value.response['Error']['Code'] == 'AccessDenied'


def test_save_without_an_etag_is_unconditional(aws):
    make_list(aws)
    another_writer_adds(aws, 'racer@example.com')
    assert storage.save_list_config(HOST, 'test-list', {'members': []}) == \
        aws.s3.etags[(settings.s3_bucket, KEY)]
    assert addresses(aws) == []
    # Without a condition, a 412 can't be a conflict, so it isn't reported as one.
    aws.s3.fail_puts(settings.s3_bucket, KEY, 'PreconditionFailed')
    with pytest.raises(ClientError):
        storage.save_list_config(HOST, 'test-list', {'members': []})


# ---------------------------------------------------------------- update_list

def add(address):
    def change(l):
        l.members.append(listobj.ListMember(address))
        return True
    return change


def test_update_list_saves_the_change(aws):
    make_list(aws)
    listobj.update_list(HOST, 'test-list', add('new@example.com'))
    assert addresses(aws) == ['admin@example.com', 'plain@example.com', 'new@example.com']
    assert aws.log == [('s3', 'get_object', KEY), ('s3', 'put_object', KEY)]


def test_update_list_without_a_change_doesnt_save(aws):
    make_list(aws)
    listobj.update_list(HOST, 'test-list', lambda l: False)
    assert aws.log == [('s3', 'get_object', KEY)]


def test_update_list_starts_again_after_a_conflict(aws, racing_writer):
    make_list(aws)
    racing_writer()
    listobj.update_list(HOST, 'test-list', add('new@example.com'))
    # The change was applied again to the list as the other writer left it.
    assert addresses(aws) == ['admin@example.com', 'plain@example.com', 'racer1@example.com', 'new@example.com']
    assert aws.log == [
        ('s3', 'get_object', KEY), ('s3', 'put_object', KEY),
        ('s3', 'get_object', KEY), ('s3', 'put_object', KEY),
        ]


def test_update_list_starts_again_after_a_reported_conflict(aws):
    make_list(aws)
    aws.s3.fail_puts(settings.s3_bucket, KEY, 'ConditionalRequestConflict', 'PreconditionFailed')
    listobj.update_list(HOST, 'test-list', add('new@example.com'))
    assert addresses(aws) == ['admin@example.com', 'plain@example.com', 'new@example.com']


def test_update_list_gives_up(aws, racing_writer):
    make_list(aws)
    racing_writer(3)
    calls = []
    with pytest.raises(ListChanged):
        listobj.update_list(HOST, 'test-list', lambda l: calls.append(1) or add('new@example.com')(l))
    assert len(calls) == 3
    assert addresses(aws) == ['admin@example.com', 'plain@example.com',
                              'racer1@example.com', 'racer2@example.com', 'racer3@example.com']


def test_update_list_attempts(aws, racing_writer):
    make_list(aws)
    racing_writer(1)
    with pytest.raises(ListChanged):
        listobj.update_list(HOST, 'test-list', add('new@example.com'), attempts=1)


def test_update_list_of_a_missing_list(aws):
    with pytest.raises(ListNotFound):
        listobj.update_list(HOST, 'test-list', add('new@example.com'))


def test_update_list_of_a_list_deleted_meanwhile(aws):
    make_list(aws)

    def change(l):
        aws.s3.delete_object(Bucket=settings.s3_bucket, Key=KEY)
        return add('new@example.com')(l)
    with pytest.raises(ListNotFound):
        listobj.update_list(HOST, 'test-list', change)


# ---------------------------------------------------------------- bounces

BOUNCE = read_bytes(FIXTURES, 'bounces', 'synthetic', 'ses-permanent.eml')


@freeze_time(NOW)
def test_bounce_is_recorded_again_after_a_conflict(aws, racing_writer):
    make_list(aws)
    racing_writer()
    listobj.List.handle_bounce_to('test-list+plain=example.com+bounce@example.org', parse_message(BOUNCE))
    members = yaml.safe_load(stored_list_config(aws, 'test-list'))['members']
    # Both the other writer's subscription and the bounce were kept.
    assert [m.address for m in members] == ['admin@example.com', 'plain@example.com', 'racer1@example.com']
    assert list(members[1].bounces.values()) == [ResponseType.hard]


# ---------------------------------------------------------------- email commands

@pytest.mark.parametrize('user, cmd', [
    ('new@example.com', 'subscribe'),
    ('plain@example.com', 'unsubscribe'),
    ('plain@example.com', 'setflag vacation'),
    ('admin@example.com', 'set subject-tag Tag'),
    ])
def test_command_conflict_says_try_again(aws, racing_writer, user, cmd):
    make_list(aws, **{'open-subscription': True})
    racing_writer()
    before = addresses(aws)
    assert commands.run(user=user, cmd='list test-list@example.org ' + cmd) == COMMAND_CONFLICT
    # The command didn't overwrite the other writer's change, and isn't retried.
    assert addresses(aws) == before + ['racer1@example.com']
    assert aws.log.count(('s3', 'put_object', KEY)) == 1


# ---------------------------------------------------------------- API

def call(**event):
    # The Lambda runtime JSON-serializes the return value.
    return json.loads(json.dumps(handle_api(event)))


@pytest.mark.parametrize('event', [
    dict(Action='UpdateList', Data={'subject-tag': 'Tag'}),
    dict(Action='CreateMember', MemberAddress='new@example.com'),
    dict(Action='UpdateMember', MemberAddress='plain@example.com', Data={'flags': ['vacation']}),
    dict(Action='DeleteMember', MemberAddress='plain@example.com'),
    ])
def test_api_conflict_is_409(aws, racing_writer, event):
    make_list(aws)
    racing_writer()
    before = addresses(aws)
    assert call(ListAddress='test-list@example.org', **event) == API_CONFLICT
    assert addresses(aws) == before + ['racer1@example.com']
    assert aws.log.count(('s3', 'put_object', KEY)) == 1
