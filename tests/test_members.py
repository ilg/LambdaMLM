# -*- coding: utf-8 -*-
"""List members, flags, bounce scoring and membership permissions."""

from datetime import datetime

import pytest
import yaml
from freezegun import freeze_time

from email_utils import ResponseType, bounce_defaults
from list_exceptions import AlreadySubscribed, InsufficientPermissions, NotSubscribed
from list_member import ListMember, MemberFlag
from list_member_container import ListMemberContainer


def flags(*names):
    return set(MemberFlag[n] for n in names)


# ---------------------------------------------------------------- flags

def test_member_flag_names_and_order():
    # user_own_flags lists flags in this order.
    assert [f.name for f in MemberFlag] == [
        'modPost', 'preapprove', 'noPost', 'moderator', 'superAdmin', 'admin',
        'vacation', 'echoPost', 'bouncing']


def test_userlevel_flags():
    assert MemberFlag.userlevel_flags() == [MemberFlag.vacation, MemberFlag.echoPost]


def test_response_type_names():
    assert [t.name for t in ResponseType] == ['hard', 'soft', 'complaint', 'unknown']


def test_flag_yaml_tags():
    text = yaml.safe_dump({'f': MemberFlag.admin, 'b': ResponseType.hard}, default_flow_style=False)
    assert text == "b: !bouncekind 'hard'\nf: !flag 'admin'\n"
    assert yaml.safe_load(text) == {'f': MemberFlag.admin, 'b': ResponseType.hard}


# ---------------------------------------------------------------- ListMember

def test_member_constructor_keeps_only_flags():
    m = ListMember('a@example.com', MemberFlag.admin, 'not a flag', MemberFlag.echoPost)
    assert m.address == 'a@example.com'
    assert m.flags == flags('admin', 'echoPost')


def test_member_defaults_for_missing_attributes():
    # Loading from YAML doesn't call __init__, so missing keys fall back here.
    m = ListMember.__new__(ListMember)
    m.address = 'a@example.com'
    assert m.flags == set()
    assert m.name is None
    with pytest.raises(AttributeError):
        m.bounces


def test_member_repr():
    m = ListMember('a@example.com', MemberFlag.admin)
    m.name = 'Alice'
    assert repr(m) == 'ListMember(Alice <a@example.com>, flags: admin)'


def test_member_dict():
    m = ListMember('a@example.com', MemberFlag.admin, MemberFlag.echoPost)
    d = m.dict()
    assert sorted(d.pop('flags')) == ['admin', 'echoPost']
    assert d == {'address': 'a@example.com', 'name': None}


def test_member_update_from_dict():
    m = ListMember('a@example.com', MemberFlag.admin)
    m.update_from_dict({'address': 'b@example.com', 'name': 'Bee', 'flags': ['vacation']})
    assert (m.address, m.name, m.flags) == ('b@example.com', 'Bee', flags('vacation'))
    m.update_from_dict({})
    assert (m.address, m.name, m.flags) == ('b@example.com', 'Bee', flags('vacation'))


def test_member_update_from_dict_unknown_flag():
    with pytest.raises(KeyError):
        ListMember('a@example.com').update_from_dict({'flags': ['nope']})


@pytest.mark.parametrize('member_flags, from_address, expected', [
    ((), 'other@example.com', True),
    ((), 'a@example.com', False),
    (('echoPost',), 'a@example.com', True),
    (('vacation',), 'other@example.com', False),
    (('bouncing',), 'other@example.com', False),
    (('vacation', 'echoPost'), 'a@example.com', False),
    (('bouncing', 'echoPost'), 'a@example.com', False),
    (('admin', 'moderator'), 'other@example.com', True),
    ])
def test_can_receive_from(member_flags, from_address, expected):
    m = ListMember('a@example.com', *[MemberFlag[f] for f in member_flags])
    assert m.can_receive_from(from_address) is expected


def test_can_receive_from_is_case_sensitive():
    m = ListMember('A@example.com')
    assert m.can_receive_from('a@example.com') is True


@freeze_time('2026-09-14 12:00:00.123456')
def test_add_response():
    m = ListMember('a@example.com')
    m.add_response(ResponseType.hard)
    assert m.bounces == {datetime(2026, 9, 14, 12, 0, 0, 123456): ResponseType.hard}
    with freeze_time('2026-09-15 08:00:00'):
        m.add_response(ResponseType.soft)
    assert len(m.bounces) == 2


# ---------------------------------------------------------------- bounce score

WEIGHTS = bounce_defaults.bounce_weights
DECAY = bounce_defaults.bounce_decay_factor


def test_bounce_defaults():
    assert bounce_defaults.bounce_score_threshold == 2.0
    assert WEIGHTS == {
        ResponseType.hard: 1.0, ResponseType.soft: 0.5,
        ResponseType.complaint: 3.0, ResponseType.unknown: 0.0}
    assert DECAY == 0.8


def test_bounce_score_without_bounces():
    assert ListMember('a@example.com').bounce_score(WEIGHTS, DECAY) == 0


@freeze_time('2026-09-14 12:00:00')
def test_bounce_score_documented_example():
    # The example in docs/technical.md.
    m = ListMember('a@example.com')
    m.bounces = {
        datetime(2026, 9, 14, 1, 0): ResponseType.hard,
        datetime(2026, 9, 14, 2, 0): ResponseType.soft,
        datetime(2026, 9, 13, 3, 0): ResponseType.hard,
        datetime(2026, 9, 12, 4, 0): ResponseType.soft,
    }
    assert m.bounce_score(WEIGHTS, DECAY) == pytest.approx(1.0 + 0.8 + 0.5 * 0.8 * 0.8)


@freeze_time('2026-09-14 00:00:01')
def test_bounce_score_uses_calendar_days():
    m = ListMember('a@example.com')
    # One second before midnight counts as a full day ago.
    m.bounces = {datetime(2026, 9, 13, 23, 59, 59): ResponseType.hard}
    assert m.bounce_score(WEIGHTS, DECAY) == pytest.approx(0.8)


@freeze_time('2026-09-14 12:00:00')
def test_bounce_score_complaint_and_unknown():
    m = ListMember('a@example.com')
    m.bounces = {
        datetime(2026, 9, 14, 1, 0): ResponseType.unknown,
        datetime(2026, 9, 10, 1, 0): ResponseType.complaint,
    }
    assert m.bounce_score(WEIGHTS, DECAY) == pytest.approx(3.0 * 0.8 ** 4)


# ---------------------------------------------------------------- container

class Container(ListMemberContainer):
    def __init__(self, *members):
        self.members = list(members)
        self.saves = 0

    def _save(self):
        self.saves += 1


def member(address, *names):
    return ListMember(address, *[MemberFlag[n] for n in names])


def test_moderator_addresses():
    c = Container(member('a@example.com', 'moderator'), member('b@example.com'),
                  member('c@example.com', 'moderator', 'admin'))
    assert c.moderator_addresses == ['a@example.com', 'c@example.com']


def test_member_with_address():
    a = member('a@example.com')
    c = Container(a, member('b@example.com'))
    assert c.member_with_address('a@example.com') is a
    assert c.member_with_address('z@example.com') is None


def test_member_with_address_is_case_sensitive():
    c = Container(member('Mixed.Case@example.com'))
    assert c.member_with_address('mixed.case@example.com') is None


@pytest.mark.xfail(strict=True, reason='Step 3: member lookups should ignore case.')
def test_member_with_address_ignores_case():
    m = member('Mixed.Case@example.com')
    assert Container(m).member_with_address('mixed.case@example.com') is m


class TestAddressWillModifyAddress(object):
    def container(self):
        return Container(
                member('plain@example.com'),
                member('admin@example.com', 'admin'),
                member('admin2@example.com', 'admin'),
                member('super@example.com', 'admin', 'superAdmin'),
                member('superonly@example.com', 'superAdmin'))

    def test_self_is_always_allowed(self):
        self.container().address_will_modify_address('plain@example.com', 'plain@example.com')
        # Even for addresses that aren't members.
        self.container().address_will_modify_address('x@example.com', 'x@example.com')

    def test_non_admin_cannot_modify_others(self):
        with pytest.raises(InsufficientPermissions):
            self.container().address_will_modify_address('plain@example.com', 'x@example.com')

    def test_admin_can_modify_non_admins(self):
        c = self.container()
        c.address_will_modify_address('admin@example.com', 'plain@example.com')
        c.address_will_modify_address('admin@example.com', 'nonmember@example.com')

    def test_admin_cannot_modify_admins(self):
        with pytest.raises(InsufficientPermissions):
            self.container().address_will_modify_address('admin@example.com', 'admin2@example.com')

    def test_super_admin_can_modify_admins(self):
        self.container().address_will_modify_address('super@example.com', 'admin2@example.com')

    def test_super_admin_flag_alone_is_not_admin(self):
        with pytest.raises(InsufficientPermissions):
            self.container().address_will_modify_address('superonly@example.com', 'plain@example.com')

    def test_non_member_acting_on_another_address_crashes(self):
        with pytest.raises(AttributeError):
            self.container().address_will_modify_address('x@example.com', 'plain@example.com')

    @pytest.mark.xfail(strict=True, raises=AttributeError,
                       reason='Step 3 (optional): a non-member should get InsufficientPermissions.')
    def test_non_member_acting_on_another_address(self):
        with pytest.raises(InsufficientPermissions):
            self.container().address_will_modify_address('x@example.com', 'plain@example.com')


def test_add_member():
    c = Container()
    c.add_member('Alice Example <alice@example.com>')
    (m,) = c.members
    assert (m.address, m.name, m.flags) == ('alice@example.com', 'Alice Example', set())
    assert c.saves == 1


def test_add_member_keeps_address_case():
    c = Container()
    c.add_member('Alice.Example@Example.com')
    assert c.members[0].address == 'Alice.Example@Example.com'
    assert c.members[0].name == ''


def test_add_member_unparseable():
    # How the production member with `address: ''` came about.
    c = Container()
    c.add_member(' ')
    assert (c.members[0].address, c.members[0].name) == ('', '')


def test_add_member_already_subscribed():
    c = Container(member('alice@example.com'))
    with pytest.raises(AlreadySubscribed):
        c.add_member('Alice <alice@example.com>')
    assert c.saves == 0


def test_add_member_already_subscribed_is_case_sensitive():
    c = Container(member('alice@example.com'))
    c.add_member('ALICE@example.com')
    assert len(c.members) == 2


def test_remove_member():
    a = member('a@example.com')
    c = Container(a, member('b@example.com'))
    c.remove_member(a)
    assert [m.address for m in c.members] == ['b@example.com']
    assert c.saves == 1


def test_remove_member_none():
    with pytest.raises(NotSubscribed):
        Container().remove_member(None)
