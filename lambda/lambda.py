from __future__ import print_function

from ses import email_message_from_s3_bucket, event_msg_is_to_command
from cnc import handle_command

from config import email_bucket

def lambda_handler(event, context):
    with email_message_from_s3_bucket(event, email_bucket) as msg:
        command_address = event_msg_is_to_command(event, msg)
        if command_address:
            print('Message addressed to command ({}).'.format(command_address))
            handle_command(command_address, msg)
            return
        # TODO: handle non-commands
