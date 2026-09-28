"""Sending mail through SES.  Every message the function sends goes out here."""

import email.policy
import re

import aws_clients


class _SendPolicy(email.policy.Compat32):
    """How messages are written when they're sent or stored.

    Like the default compat32 policy, except that a header that's already
    folded, or short enough not to need folding, is written exactly as it is.
    The default re-wraps every long header, which would rewrite the trace
    headers of every post.  Lines end in CRLF, the canonical form for email
    and the form SES stores incoming mail in.
    """
    def _fold(self, name, value, sanitize):
        if isinstance(value, str) and not any('\udc80' <= c <= '\udcff' for c in value):
            lines = re.split(r'\r?\n', value)
            if len(lines) > 1 or len(name) + 2 + len(value) <= self.max_line_length:
                return '{}: {}{}'.format(name, self.linesep.join(lines), self.linesep)
        return super()._fold(name, value, sanitize)


SEND_POLICY = _SendPolicy(linesep='\r\n')


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
