from __future__ import print_function

from contextlib import contextmanager

import datetime
import email

import boto3

from ses import email_message_from_s3_bucket, msg_get_header

email_bucket = 'lambdamlm'

ses = boto3.client('ses')

def lambda_handler(event, context):
    with email_message_from_s3_bucket(event, email_bucket) as msg:
        # Validate that the control address is the only recipient.
        recipients = event['Records'][0]['ses']['receipt']['recipients']
        if len(recipients) != 1:
            print("Too many recipients (SES receipt).")
            return
        if not recipients[0].startswith('lambda@'):
            print("Unexpected recipient (SES receipt).")
            return

        # Validate that the control address is the only destination.
        destination = event['Records'][0]['ses']['mail']['destination']
        if len(destination) != 1:
            print("Too many recipients (SES destination).")
            return
        if not destination[0].startswith('lambda@'):
            print("Unexpected recipient (SES destination).")
            return

        # Validate the To: header.
        _, to_address = email.utils.parseaddr(msg_get_header(msg, 'to'))
        print("To: " + to_address)
        if not to_address.startswith('lambda@'):
            print("Unexpected recipient (To: header).")
            return

        # Grab the Reply-To: address and subject
        reply_to = msg_get_header(msg, 'reply-to')
        if reply_to is None:
            reply_to = msg_get_header(msg, 'from')
        if reply_to is None:
            reply_to = msg_get_header(msg, 'sender')
        if reply_to is None:
            print("Failed to get an email address from the Reply-To, From, or Sender headers.")
            return
        subject = msg_get_header(msg, 'subject')
        print("Subject: " + subject)

        response = ses.send_email(
                Source=to_address,
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

