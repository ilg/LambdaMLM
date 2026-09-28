"""Signed commands: signature values and token validation."""

from datetime import timedelta

import pytest
from freezegun import freeze_time

import golden
import settings
import signing

ADDRESS = 'alice@example.com'
COMMAND = 'list alpha-list@example.org subscribe'
# Longer than the 64-byte HMAC block size and containing a backslash, like the
# production key (whose value isn't known here).  Keys longer than the block
# size are hashed first, which is why a unicode key works on Python 2 for them.
LONG_UNICODE_KEY = ('This is a long ASCII signing key used only by the tests, '
                    'with a backslash \\ in it, long enough to be hashed first.')
NOW = '2026-09-14 12:00:00'


def use_key(monkeypatch, key):
    monkeypatch.setattr(settings, 'signing_key', lambda: key)


@pytest.fixture
def long_unicode_key(monkeypatch):
    use_key(monkeypatch, LONG_UNICODE_KEY)


def split_signed(signed):
    match = signing.signed_cmd_regex.match(signed)
    assert match
    return match.group('cmd'), match.group('signature'), match.group('timestamp')


def test_signature_values(monkeypatch):
    values = {}
    inputs = [
        '{} 20260914130000 {}'.format(ADDRESS, COMMAND),
        '  {} 20260914130000 {}  '.format(ADDRESS, COMMAND),
        'Alice <alice@example.com> 20260914130000 {}'.format(COMMAND),
        '',
    ]
    for i, text in enumerate(inputs):
        values['test-key/{}'.format(i)] = signing.signature(text)
    use_key(monkeypatch, LONG_UNICODE_KEY)
    for i, text in enumerate(inputs):
        values['long-unicode-key/{}'.format(i)] = signing.signature(text)
    golden.check_json('signatures.json', values)


def test_signature_ignores_surrounding_whitespace():
    assert signing.signature(' x ') == signing.signature('x')


def test_signature_shape():
    # 20-byte SHA-1 HMAC, base64: 27 characters and one '=' of padding.
    sig = signing.signature('anything')
    assert len(sig) == 28
    assert sig.endswith('=')


@freeze_time(NOW)
def test_sign_format():
    signed = signing.sign(COMMAND, ADDRESS)
    cmd, sig, timestamp = split_signed(signed)
    assert cmd == COMMAND
    # Default validity is settings.signed_validity_interval (1 hour in tests).
    assert timestamp == '20260914130000'
    assert sig == signing.signature(' '.join([ADDRESS, timestamp, COMMAND]))
    assert signed == '{} {}{}'.format(COMMAND, sig, timestamp)


@freeze_time(NOW)
def test_sign_with_validity_duration():
    signed = signing.sign(COMMAND, ADDRESS, validity_duration=timedelta(days=3))
    assert split_signed(signed)[2] == '20260917120000'


@freeze_time(NOW)
def test_sign_with_long_unicode_key(long_unicode_key):
    signed = signing.sign(COMMAND, ADDRESS)
    assert signing.get_signed_command(signed, ADDRESS) == COMMAND


def signed_now():
    with freeze_time(NOW):
        return signing.sign(COMMAND, ADDRESS)


def test_get_signed_command_round_trip():
    signed = signed_now()
    with freeze_time('2026-09-14 12:59:59'):
        assert signing.get_signed_command(signed, ADDRESS) == COMMAND


def test_get_signed_command_accepts_extra_leading_text():
    # handle_command strips everything up to the last ':' first, but the
    # regex itself allows anything before the signature.
    signed = signed_now()
    with freeze_time(NOW):
        assert signing.get_signed_command('   ' + signed, ADDRESS) == COMMAND


def test_unsigned_subject():
    with pytest.raises(signing.NotSignedException):
        signing.get_signed_command(COMMAND, ADDRESS)


def test_expired_signature():
    signed = signed_now()
    with freeze_time('2026-09-14 13:00:01'):
        with pytest.raises(signing.ExpiredSignatureException):
            signing.get_signed_command(signed, ADDRESS)


def test_wrong_address():
    signed = signed_now()
    with freeze_time(NOW):
        with pytest.raises(signing.InvalidSignatureException):
            signing.get_signed_command(signed, 'bob@example.com')


def test_address_case_matters():
    signed = signed_now()
    with freeze_time(NOW):
        with pytest.raises(signing.InvalidSignatureException):
            signing.get_signed_command(signed, 'Alice@example.com')


def test_tampered_command():
    cmd, sig, timestamp = split_signed(signed_now())
    with freeze_time(NOW):
        with pytest.raises(signing.InvalidSignatureException):
            signing.get_signed_command(
                    '{} {}{}'.format(cmd + ' extra', sig, timestamp), ADDRESS)


def test_signed_for_bare_address_accepts_named_address():
    signed = signed_now()
    with freeze_time(NOW):
        assert signing.get_signed_command(signed, 'Alice <alice@example.com>') == COMMAND


def test_signed_for_named_address_rejects_bare_address():
    with freeze_time(NOW):
        signed = signing.sign(COMMAND, 'Alice <alice@example.com>')
        assert signing.get_signed_command(signed, 'Alice <alice@example.com>') == COMMAND
        with pytest.raises(signing.InvalidSignatureException):
            signing.get_signed_command(signed, ADDRESS)


def test_short_unicode_key(monkeypatch):
    # Issue #34: a short unicode key crashed hmac on Python 2.  It signs
    # exactly like the same key as bytes.
    use_key(monkeypatch, 'short unicode key')
    text_signature = signing.signature('anything')
    use_key(monkeypatch, b'short unicode key')
    assert text_signature == signing.signature('anything')


def test_bytes_key(monkeypatch):
    use_key(monkeypatch, LONG_UNICODE_KEY.encode('utf-8'))
    bytes_signature = signing.signature('anything')
    use_key(monkeypatch, LONG_UNICODE_KEY)
    assert signing.signature('anything') == bytes_signature


def test_non_ascii_command():
    cmd = 'list alpha-list@example.org subscribe "José <j@example.com>"'
    with freeze_time(NOW):
        assert signing.get_signed_command(signing.sign(cmd, ADDRESS), ADDRESS) == cmd


def test_impossible_timestamp_is_invalid():
    signed = '{} {}{}'.format(COMMAND, signing.signature('x'), '20261399000000')
    with pytest.raises(signing.InvalidSignatureException):
        signing.get_signed_command(signed, ADDRESS)
