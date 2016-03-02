from __future__ import print_function

from sestools import email_message_for_event, event_msg_is_to_command, msg_get_header, recipient_destination_overlap
from control import handle_command
from api import handle_api

from listobj import List

def lambda_handler(event, context):
    if 'Records' not in event:
        return handle_api(event)
        # API
    with email_message_for_event(event) as msg:
        # If it's a command, handle it as such.
        command_address = event_msg_is_to_command(event, msg)
        if command_address:
            print('Message addressed to command ({}).'.format(command_address))
            handle_command(command_address, msg)
            return
        
        print('Message from {}.'.format(msg_get_header(msg, 'from')))
        recipients = recipient_destination_overlap(event)

        # See if the message looks like it's a bounce.
        for r in recipients:
            if '+bounce@' in r:
                List.handle_bounce_to(r, msg)
                # Don't do any further processing with this email.
                return

        # See if the message was sent to any known lists.
        for l in List.lists_for_addresses(recipients):
            print('Sending to list {}.'.format(l.address))
            l.send(msg)
