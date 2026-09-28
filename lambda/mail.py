"""Sending mail through SES.  Every message the function sends goes out here."""

import aws_clients


def send_raw(source, destination, data):
    """Send a complete message (bytes) to one recipient."""
    return aws_clients.ses().send_raw_email(
            Source=source,
            Destinations=[ destination, ],
            RawMessage={ 'Data': data, },
            )


def send_text(source, destination, subject, body):
    """Send a plain-text message, such as a command's reply."""
    return aws_clients.ses().send_email(
            Source=source,
            Destination={
                'ToAddresses': [ destination, ],
                },
            Message={
                'Subject': { 'Data': subject, },
                'Body': {
                    'Text': { 'Data': body, },
                    }
                },
            )
