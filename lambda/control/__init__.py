from __future__ import print_function

import base64
import datetime
import hmac
import hashlib
import re

timestamp_format = '%Y%m%d%H%M%S'

signed_cmd_regex = re.compile(r'^(?P<cmd>.+)\s+(?P<signature>[\da-zA-Z+/]{27}=)(?P<timestamp>\d{14})$')

from config import signing_key, signed_validity_interval
from sestools import msg_get_header, msg_get_response_address

import boto3

ses = boto3.client('ses')

from commands import run

class NotSignedException(Exception):
    pass

class ExpiredSignatureException(Exception):
    pass

class InvalidSignatureException(Exception):
    pass

def handle_command(command_address, msg):
    auto_submitted = msg_get_header(msg, 'auto-submitted')
    if auto_submitted and auto_submitted.lower() != 'no':
        # Auto-submitted: header, https://www.iana.org/assignments/auto-submitted-keywords/auto-submitted-keywords.xhtml
        print("Message appears to be automatically generated ({}), so ignoring it.".format(auto_submitted))
        return

    # Grab the address to which to respond and the subject
    reply_to = msg_get_response_address(msg)
    if reply_to is None:
        print("Failed to get an email address from the Reply-To, From, or Sender headers.")
        return
    subject = msg_get_header(msg, 'subject').replace('\n', ' ')
    print("Subject: " + subject)
    print("Responding to: " + reply_to)

    # Strip off any re:, fwd:, etc. (everything up to the last :, then trim whitespace)
    if ':' in subject:
        subject = subject[subject.rfind(':') + 1:]
    subject = subject.strip()

    try:
        cmd = get_signed_command(subject, reply_to)
    except ExpiredSignatureException:
        # TODO (maybe): Reply to the sender to tell them the signature was expired?  Or send a newly-signed message?
        print("Expired signature.")
        return
    except InvalidSignatureException:
        # Do nothing.
        print("Invalid signature.")
        return
    except NotSignedException:
        # If the subject isn't a signed command...
        # TODO (maybe): ... check if the reply_to is allowed to run the specific command with the given parameters...
        # ... and reply with a signed command for the recipient to send back (by replying).
        print("Signing command: {}".format(subject))
        response = send_response(
                source=command_address,
                destination=reply_to,
                subject='Re: {}'.format(sign(subject, reply_to)),
                body='To verify the origin of the command, please reply to this email.',
                )
        return

    # TODO (maybe): allow commands in body?
    
    # Execute the command.
    output = run(user=reply_to, cmd=cmd)

    # Reply with the output/response.
    response = send_response(
            source=command_address,
            destination=reply_to,
            subject='Re: {}'.format(subject),
            body='Output of "{}":\n\n{}'.format(cmd, output),
            )

def send_response(source, destination, subject, body):
    return ses.send_email(
            Source=source,
            Destination={
                'ToAddresses': [ destination, ],
                },
            Message={
                'Subject': { 'Data': subject, },
                'Body': {
                    'Text': { 'Data': body, },
                    }
                },
            )

def get_signed_command(subject, address):
    match = signed_cmd_regex.match(subject)
    if not match:
        raise NotSignedException
    (cmd, timestamp, sig) = ('  ' + subject).rsplit(' ', 2)
    cmd = match.group('cmd').strip()
    sig = match.group('signature')
    timestamp = match.group('timestamp')
    if not sig or not timestamp:
        raise NotSignedException
    timestamp_age = datetime.datetime.now() - datetime.datetime.strptime(timestamp, timestamp_format)
    try:
        # Check that the timestamp is recent enough.
        if timestamp_age > signed_validity_interval:
            raise ExpiredSignatureException
    except ValueError:
        raise InvalidSignatureException
    if not hmac.compare_digest(base64.b64decode(signature(' '.join([ address, timestamp, cmd, ]))), base64.b64decode(sig)):
        raise InvalidSignatureException
    return cmd

def signature(cmd):
    return base64.b64encode(hmac.new(signing_key, cmd.strip(), hashlib.sha1).digest())

def sign(subject, reply_to):
    timestamp = datetime.datetime.now().strftime(timestamp_format)
    return '{} {}{}'.format(
            subject,
            signature(' '.join([ reply_to, timestamp, subject, ])),
            timestamp,
            )
