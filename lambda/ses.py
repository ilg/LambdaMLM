from __future__ import print_function

from contextlib import contextmanager

import email
import email.header
import boto3

s3 = boto3.client('s3')

@contextmanager
def email_message_from_s3_bucket(event, email_bucket):
    key = event['Records'][0]['ses']['mail']['messageId']
    
    # Get the email from S3
    try:
        response = s3.get_object(Bucket=email_bucket, Key=key)
    except Exception as e:
        print(e)
        print('Error getting object {} from bucket {}. Make sure they exist and your bucket is in the same region as this function.'.format(key, email_bucket))
        raise e
    
    try:
        yield email.message_from_file(response['Body'])
    finally:
        # Clean up: delete the email from S3
        try:
            response = s3.delete_object(Bucket=email_bucket, Key=key)
            print("Removed email from S3.")
        except Exception as e:
            print(e)
            print('Error removing object {} from bucket {}. Make sure they exist and your bucket is in the same region as this function.'.format(key, bucket))
            raise e

def msg_get_header(msg, header_name):
    raw = msg[header_name]
    if raw is None:
        return None
    return unicode(email.header.make_header(email.header.decode_header(raw)))

