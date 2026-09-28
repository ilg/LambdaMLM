"""The Lambda function's entry point.

An event with Records is mail SES received; anything else is a direct call
to the API.
"""

import copy

from api import handle_api
from control import handle_command
from listobj import List
from sestools import email_message_for_event, event_msg_is_to_command, event_recipients, msg_get_header


def lambda_handler(event, context):
    if 'Records' not in event:
        return handle_api(event)
    return handle_ses_event(event)


def handle_ses_event(event):
    """Handle mail SES received: a command, a bounce, or a post to lists."""
    with email_message_for_event(event) as msg:
        # If it's a command, handle it as such.
        command_address = event_msg_is_to_command(event, msg)
        if command_address:
            print('Message addressed to command ({}).'.format(command_address))
            handle_command(command_address, msg)
            return

        print('Message from {}.'.format(msg_get_header(msg, 'from')))
        recipients = event_recipients(event)

        # See if the message looks like it's a bounce.
        for r in recipients:
            if '+bounce@' in r:
                List.handle_bounce_to(r, msg)
                # Don't do any further processing with this email.
                return

        # See if the message was sent to any known lists.
        for l in List.lists_for_addresses(recipients):
            print('Sending to list {}.'.format(l.address))
            # send() rewrites the message's headers, so each list gets its own copy.
            l.send(copy.deepcopy(msg))
