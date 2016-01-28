from __future__ import print_function

from ses import email_message_from_s3_bucket, event_msg_is_to_command, msg_get_header, recipient_destination_overlap
from cnc import handle_command

import boto3

ses = boto3.client('ses')

from config import email_bucket

from listcfg import ListConfiguration

def lambda_handler(event, context):
    with email_message_from_s3_bucket(event, email_bucket) as msg:
        # If it's a command, handle it as such.
        command_address = event_msg_is_to_command(event, msg)
        if command_address:
            print('Message addressed to command ({}).'.format(command_address))
            handle_command(command_address, msg)
            return
        
        del msg['DKIM-Signature']
        print('Message from {}.'.format(msg_get_header(msg, 'from')))
        # See if the message was sent to any known lists.
        for addr in recipient_destination_overlap(event):
            print('Looking for list {}...'.format(addr))
            try:
                cfg = ListConfiguration(addr)
            except:
                continue
            print('Found list {}.'.format(addr))
            del msg['Sender']
            msg['Sender'] = cfg.address
            for user, flags in cfg.config['users'].iteritems():
                print('> Sending to user {}.'.format(user))
                ses.send_raw_email(
                        Source=cfg.address,
                        Destinations=[ user, ],
                        RawMessage={ 'Data': msg.as_string(), },
                        )
            
