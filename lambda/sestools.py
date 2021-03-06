from __future__ import print_function

from contextlib import contextmanager

import email
import email.header
import boto3

s3 = boto3.client('s3')

from config import command_user, s3_bucket, s3_incoming_email_prefix
command_address_prefix = command_user + '@'

@contextmanager
def email_message_for_event(event):
    key = s3_incoming_email_prefix + event['Records'][0]['ses']['mail']['messageId']
    
    # Get the email from S3
    try:
        response = s3.get_object(Bucket=s3_bucket, Key=key)
    except Exception as e:
        print(e)
        print('Error getting object {} from bucket {}. Make sure they exist and your bucket is in the same region as this function.'.format(key, s3_bucket))
        raise e
    
    try:
        yield email.message_from_file(response['Body'])
    finally:
        # Clean up: delete the email from S3
        try:
            response = s3.delete_object(Bucket=s3_bucket, Key=key)
            print("Removed email from S3.")
        except Exception as e:
            print(e)
            print('Error removing object {} from bucket {}. Make sure they exist and your bucket is in the same region as this function.'.format(key, s3_bucket))
            raise e

def msg_get_header(msg, header_name):
    raw = msg[header_name]
    if raw is None:
        return None
    return unicode(email.header.make_header(email.header.decode_header(raw)))

def msg_get_response_address(msg):
    reply_to = msg_get_header(msg, 'reply-to')
    if reply_to is None:
        reply_to = msg_get_header(msg, 'from')
    if reply_to is None:
        reply_to = msg_get_header(msg, 'sender')
    return reply_to

def recipient_destination_overlap(event):
    recipients = set(event['Records'][0]['ses']['receipt']['recipients'])
    destination = set(event['Records'][0]['ses']['mail']['destination'])
    return recipients & destination

def event_msg_is_to_command(event, msg):
    # Validate that the control address is the only recipient.
    recipients = event['Records'][0]['ses']['receipt']['recipients']
    if len(recipients) != 1:
        #print("Too many recipients (SES receipt).")
        return False
    if not recipients[0].startswith(command_address_prefix):
        #print("Unexpected recipient (SES receipt).")
        return False

    # Validate that the control address is the only destination.
    destination = event['Records'][0]['ses']['mail']['destination']
    if len(destination) != 1:
        #print("Too many recipients (SES destination).")
        return False
    if not destination[0].startswith(command_address_prefix):
        #print("Unexpected recipient (SES destination).")
        return False

    # Validate the To: header.
    _, to_address = email.utils.parseaddr(msg_get_header(msg, 'to'))
    #print("To: " + to_address)
    if not to_address.startswith(command_address_prefix):
        #print("Unexpected recipient (To: header).")
        return False

    return to_address
