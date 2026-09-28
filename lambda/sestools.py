from contextlib import contextmanager

import email
import email.header

import settings
import storage

@contextmanager
def email_message_for_event(event):
    message_id = event['Records'][0]['ses']['mail']['messageId']
    key = storage.incoming_key(message_id)

    # Get the email from S3
    try:
        data = storage.incoming_message(message_id)
    except Exception as e:
        print(e)
        print('Error getting object {} from bucket {}. Make sure they exist and your bucket is in the same region as this function.'.format(key, settings.s3_bucket))
        raise e
    
    yield email.message_from_bytes(data)

    # Clean up: delete the email from S3.  This only happens once the email has
    # been handled; if handling raised, the email stays in S3 so it isn't lost.
    try:
        storage.delete_incoming_message(message_id)
        print("Removed email from S3.")
    except Exception as e:
        print(e)
        print('Error removing object {} from bucket {}. Make sure they exist and your bucket is in the same region as this function.'.format(key, settings.s3_bucket))
        raise e

def msg_get_header(msg, header_name):
    raw = msg[header_name]
    if raw is None:
        return None
    chunks = []
    for data, charset in email.header.decode_header(raw):
        if charset == 'unknown-8bit':
            # Raw 8-bit bytes with no declared charset.  Assume UTF-8, and
            # fall back to Latin-1, which can decode any bytes.
            try:
                data.decode('utf-8')
                charset = 'utf-8'
            except UnicodeDecodeError:
                charset = 'latin-1'
        chunks.append((data, charset))
    return str(email.header.make_header(chunks))

def msg_get_response_address(msg):
    reply_to = msg_get_header(msg, 'reply-to')
    if reply_to is None:
        reply_to = msg_get_header(msg, 'from')
    if reply_to is None:
        reply_to = msg_get_header(msg, 'sender')
    return reply_to

def event_recipients(event):
    # The envelope recipients the receipt rule matched.  This deliberately
    # doesn't use mail.destination, which comes from the To: and Cc:
    # headers and so leaves out anyone the message was Bcc'd to.
    return set(event['Records'][0]['ses']['receipt']['recipients'])

def event_msg_is_to_command(event, msg):
    command_address_prefix = settings.command_user + '@'
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
