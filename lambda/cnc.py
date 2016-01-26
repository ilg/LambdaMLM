from __future__ import print_function

import datetime
import boto3

from ses import msg_get_header, msg_get_response_address

ses = boto3.client('ses')

def handle_command(command_address, msg):
    # Grab the address to which to respond and the subject
    reply_to = msg_get_response_address(msg)
    if reply_to is None:
        print("Failed to get an email address from the Reply-To, From, or Sender headers.")
        return
    subject = msg_get_header(msg, 'subject')
    print("Subject: " + subject)
    print("Responding to: " + reply_to)

    # TODO: strip everything before the last :, use argparse to parse the subject, check for hmac, ...?
    # TODO: allow commands in body?

    response = ses.send_email(
            Source=command_address,
            Destination={
                'ToAddresses': [ reply_to, ],
                },
            Message={
                'Subject': { 'Data': 'Re: {}'.format(subject), },
                'Body': {
                    'Text': { 'Data': 'You sent an email with subject "{}".'.format(subject), },
                    }
                },
            )


