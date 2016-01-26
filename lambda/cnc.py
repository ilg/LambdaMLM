from __future__ import print_function

import datetime
import hmac
import hashlib

timestamp_format = '%Y%m%d%H%M%S'

from config import signing_key
from ses import msg_get_header, msg_get_response_address

import boto3

ses = boto3.client('ses')

from cnc_commands import run

def handle_command(command_address, msg):
    # TODO: don't do anything with autoresponder responses (Auto-submitted: header, https://www.iana.org/assignments/auto-submitted-keywords/auto-submitted-keywords.xhtml)

    # Grab the address to which to respond and the subject
    reply_to = msg_get_response_address(msg)
    if reply_to is None:
        print("Failed to get an email address from the Reply-To, From, or Sender headers.")
        return
    subject = msg_get_header(msg, 'subject')
    print("Subject: " + subject)
    print("Responding to: " + reply_to)

    # Strip off any re:, fwd:, etc. (everything up to the last :, then trim whitespace)
    if ':' in subject:
        subject = subject[subject.rfind(':') + 1:]
    subject = subject.strip()

    cmd = check_signature(subject, reply_to)
    if not cmd:
        # If the subject isn't a signed command...
        # TODO (maybe): ... check if the reply_to is allowed to run the specific command with the given parameters...
        # ... and reply with a signed command for the recipient to send back (by replying).
        print("Signing command.")
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

def check_signature(subject, address):
    (cmd, timestamp, sig) = ('  ' + subject).rsplit(' ', 2)
    cmd = cmd.strip()
    sig = sig.strip()
    if not timestamp:
        return False
    timestamp_age = datetime.datetime.now() - datetime.datetime.strptime(timestamp, timestamp_format)
    try:
        # Check that the timestamp is recent enough.
        if timestamp_age > datetime.timedelta(hours=1):
            return False
    except ValueError:
        return False
    if not hmac.compare_digest(unicode(signature(' '.join([ address, cmd, timestamp, ]))), unicode(sig)):
        return False
    return cmd

def signature(cmd):
    return hmac.new(signing_key, cmd.strip(), hashlib.sha1).hexdigest()

def sign(subject, reply_to):
    timestamp = datetime.datetime.now().strftime(timestamp_format)
    return ' '.join([ subject, timestamp, signature(' '.join([ reply_to, subject, timestamp, ])), ])
