"""Signed commands: signing a command for an address, and checking one.

See docs/technical.md.  The token format and signatures are part of the
compatibility contract: tokens in flight must stay valid.
"""

import base64
import datetime
import hmac
import hashlib
import re
from email.utils import parseaddr

import settings

timestamp_format = '%Y%m%d%H%M%S'

signed_cmd_regex = re.compile(r'^(?P<cmd>.+)\s+(?P<signature>[\da-zA-Z+/]{27}=)(?P<timestamp>\d{14})$')

class NotSignedException(Exception):
    pass

class ExpiredSignatureException(Exception):
    pass

class InvalidSignatureException(Exception):
    pass

def check_signature(cmd, address, timestamp, sig):
    return hmac.compare_digest(base64.b64decode(signature(' '.join([ address, timestamp, cmd, ]))), base64.b64decode(sig))

def get_signed_command(subject, address):
    match = signed_cmd_regex.match(subject)
    if not match:
        raise NotSignedException
    cmd = match.group('cmd').strip()
    sig = match.group('signature')
    timestamp = match.group('timestamp')
    try:
        expiration = datetime.datetime.strptime(timestamp, timestamp_format)
    except ValueError:
        # Not a real date and time (month 13, say), so we didn't sign it.
        raise InvalidSignatureException
    # Check that the timestamp is recent enough.
    if datetime.datetime.now() > expiration:
        raise ExpiredSignatureException
    if not check_signature(cmd, address, timestamp, sig):
        # Maybe the command was signed for a bare email address, but the address passed in had a name with it?
        _, address = parseaddr(address)
        if not check_signature(cmd, address, timestamp, sig):
            raise InvalidSignatureException
    return cmd

def signature(cmd):
    # HMAC works on bytes.  For an ASCII key and command, UTF-8 gives the same
    # bytes, and so the same signatures, as the Python 2 code did.
    signing_key = settings.signing_key()
    key = signing_key if isinstance(signing_key, bytes) else signing_key.encode('utf-8')
    digest = hmac.new(key, cmd.strip().encode('utf-8'), hashlib.sha1).digest()
    return base64.b64encode(digest).decode('ascii')

def sign(subject, reply_to, validity_duration=None):
    if validity_duration is None:
        validity_duration = settings.signed_validity_interval
    timestamp = (datetime.datetime.now() + validity_duration).strftime(timestamp_format)
    return '{} {}{}'.format(
            subject,
            signature(' '.join([ reply_to, timestamp, subject, ])),
            timestamp,
            )
