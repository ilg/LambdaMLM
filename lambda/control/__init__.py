from sestools import msg_get_header, msg_get_response_address

import mail
# Signing moved to signing.py.  These names stay here for the code and tests
# that use them through control.
from signing import (
        timestamp_format, signed_cmd_regex, NotSignedException, ExpiredSignatureException,
        InvalidSignatureException, check_signature, get_signed_command, signature, sign)

from .commands import run

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
    subject = msg_get_header(msg, 'subject')
    if subject is None:
        # Commands are in the subject.  Replying to subjectless mail would
        # also risk loops with auto-responders.
        print("Message has no subject, so ignoring it.")
        return
    subject = subject.replace('\n', '').replace('\r', '')
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
        response = mail.send_text(
                source=command_address,
                destination=reply_to,
                subject='Re: {}'.format(sign(subject, reply_to)),
                body='To confirm and execute the command, please reply to this email.',
                )
        return

    # TODO (maybe): allow commands in body?
    
    # Execute the command.
    output = run(user=reply_to, cmd=cmd)

    # Reply with the output/response.
    response = mail.send_text(
            source=command_address,
            destination=reply_to,
            subject='Re: {}'.format(subject),
            body='Output of "{}":\n\n{}'.format(cmd, output),
            )
