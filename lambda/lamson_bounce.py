# -*- coding: utf-8 -*-
"""
Bounce analysis module for Lamson.  It uses an algorithm that tries
to simply collect the headers that are most likely found in a bounce
message, and then determine a probability based on what it finds.

Vendored into LambdaMLM from lamson/bounce.py in the lamson-bsd fork
(https://github.com/ilg/lamson-bsd, commit 0cff029), which was the only part of
Lamson LambdaMLM used.  Changes from the original:

- It reads standard-library email.message.Message objects directly, through a
  small adapter (_Part), instead of lamson.encoding.MailBase objects.  Lamson's
  from_message() also decoded message bodies, which raised EncodingError for
  some messages; bodies aren't needed here, so they aren't decoded.
- Integer division is written as // so scores are the same on Python 3.
- The bounce_to decorator, unused by LambdaMLM, is removed.
- is_hard() and is_soft() treat a missing status as Python 2 did, where
  None compared less than any number: not hard, and soft if probable.
- Status codes that aren't in the tables below (Microsoft 365's 5.1.10, say)
  no longer raise KeyError.  An unlisted detail code is described by its
  subject's "other" entry, and an unlisted class or subject generically.
- Header values are collected in the order they're found, without
  duplicates, instead of in a set.  Which value came first (the first Status,
  say) then doesn't depend on string hashing, which Python 3 randomizes.

The original license follows.

Copyright (c) 2008, Zed A. Shaw
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright
notice, this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
this list of conditions and the following disclaimer in the documentation
and/or other materials provided with the distribution.

3. Neither the name of Zed A. Shaw may be used to endorse or promote products
derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY {{COPYRIGHT HOLDER}} ''AS IS'' AND ANY
EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL {{COPYRIGHT HOLDER}} BE LIABLE FOR ANY
DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
 LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

import re
from email.header import decode_header


BOUNCE_MATCHERS = {
    'Action': re.compile(r'(failed|delayed|delivered|relayed|expanded)', re.IGNORECASE | re.DOTALL),
    'Content-Description': re.compile(r'(Notification|Undelivered Message|Delivery Report)', re.IGNORECASE | re.DOTALL),
    'Diagnostic-Code': re.compile(r'(.+);\s*([0-9\-\.]+)?\s*(.*)', re.IGNORECASE | re.DOTALL),
    'Final-Recipient': re.compile(r'(.+);\s*(.*)', re.IGNORECASE | re.DOTALL),
    'Received': re.compile(r'(.+)', re.IGNORECASE | re.DOTALL),
    'Remote-Mta': re.compile(r'(.+);\s*(.*)', re.IGNORECASE | re.DOTALL),
    'Reporting-Mta': re.compile(r'(.+);\s*(.*)', re.IGNORECASE | re.DOTALL),
    'Status': re.compile(r'([0-9]+)\.([0-9]+)\.([0-9]+)', re.IGNORECASE | re.DOTALL)
}

BOUNCE_MAX = len(BOUNCE_MATCHERS) * 2.0

PRIMARY_STATUS_CODES = {
    u'1': u'Unknown Status Code 1',
    u'2': u'Success',
    u'3': u'Temporary Failure',
    u'4': u'Persistent Transient Failure',
    u'5': u'Permanent Failure'
}

SECONDARY_STATUS_CODES = {
    u'0':   u'Other or Undefined Status',
    u'1':   u'Addressing Status',
    u'2':   u'Mailbox Status',
    u'3':   u'Mail System Status',
    u'4':   u'Network and Routing Status',
    u'5':   u'Mail Delivery Protocol Status',
    u'6':   u'Message Content or Media Status',
    u'7':   u'Security or Policy Status',
}

COMBINED_STATUS_CODES = {
    u'00': u'Not Applicable',
    u'10': u'Other address status',
    u'11': u'Bad destination mailbox address',
    u'12': u'Bad destination system address',
    u'13': u'Bad destination mailbox address syntax',
    u'14': u'Destination mailbox address ambiguous',
    u'15': u'Destination mailbox address valid',
    u'16': u'Mailbox has moved',
    u'17': u'Bad sender\'s mailbox address syntax',
    u'18': u'Bad sender\'s system address',

    u'20': u'Other or undefined mailbox status',
    u'21': u'Mailbox disabled, not accepting messages',
    u'22': u'Mailbox full',
    u'23': u'Message length exceeds administrative limit.',
    u'24': u'Mailing list expansion problem',

    u'30': u'Other or undefined mail system status',
    u'31': u'Mail system full',
    u'32': u'System not accepting network messages',
    u'33': u'System not capable of selected features',
    u'34': u'Message too big for system',

    u'40': u'Other or undefined network or routing status',
    u'41': u'No answer from host',
    u'42': u'Bad connection',
    u'43': u'Routing server failure',
    u'44': u'Unable to route',
    u'45': u'Network congestion',
    u'46': u'Routing loop detected',
    u'47': u'Delivery time expired',

    u'50': u'Other or undefined protocol status',
    u'51': u'Invalid command',
    u'52': u'Syntax error',
    u'53': u'Too many recipients',
    u'54': u'Invalid command arguments',
    u'55': u'Wrong protocol version',

    u'60': u'Other or undefined media error',
    u'61': u'Media not supported',
    u'62': u'Conversion required and prohibited',
    u'63': u'Conversion required but not supported',
    u'64': u'Conversion with loss performed',
    u'65': u'Conversion failed',

    u'70': u'Other or undefined security status',
    u'71': u'Delivery not authorized, message refused',
    u'72': u'Mailing list expansion prohibited',
    u'73': u'Security conversion required but not possible',
    u'74': u'Security features not supported',
    u'75': u'Cryptographic failure',
    u'76': u'Cryptographic algorithm not supported',
    u'77': u'Message integrity failure',
}


def _decode_header_value(value):
    """Decode any RFC 2047 encoded words in a header value to text."""
    chunks = []
    for text, charset in decode_header(value):
        if isinstance(text, bytes):
            text = text.decode(charset or 'ascii', 'replace')
        chunks.append(text)
    return u''.join(chunks)


class _Headers(object):
    """A message's headers, looked up without regard to case, first value only."""
    def __init__(self, message):
        self._message = message

    def __contains__(self, key):
        return self._message.get(key) is not None

    def __getitem__(self, key):
        return _decode_header_value(self._message.get(key))


class _Part(object):
    """Stands in for lamson.encoding.MailBase: headers, parts, and walk()."""
    def __init__(self, message):
        self.message = message
        self.headers = _Headers(message)
        if message.is_multipart():
            self.parts = [_Part(p) for p in message.get_payload()]
        else:
            self.parts = []

    def walk(self):
        # Like MailBase.walk(), this doesn't include the part itself.
        for p in self.parts:
            yield p
            for x in p.walk():
                yield x


def match_bounce_headers(msg):
    """
    Goes through the headers in a potential bounce message recursively
    and collects all the answers for the usual bounce headers.
    """
    matches = {'Content-Description-Parts': {}}
    for part in msg.walk():
        for k in BOUNCE_MATCHERS:
            if k in part.headers:
                if k not in matches:
                    matches[k] = []

                # kind of an odd place to put this, but it's the easiest way
                if k == 'Content-Description':
                    matches['Content-Description-Parts'][part.headers[k].lower()] = part

                if part.headers[k] not in matches[k]:
                    matches[k].append(part.headers[k])

    return matches


def detect(message):
    """
    Given a message (an email.message.Message), this will calculate a
    probability score based on possible bounce headers it finds and return a
    BounceAnalyzer object for further analysis.

    The detection algorithm is very simple but still accurate.  For each header
    it finds it adds a point to the score.  It then uses the regex in BOUNCE_MATCHERS
    to see if the value of that header is parseable, and if it is it adds another
    point to the score.  The final probability is based on how many headers and matchers
    were found out of the total possible.

    Finally, a header will be included in the score if it doesn't match in value, but
    it WILL NOT be included in the headers used by BounceAnalyzer to give you meanings
    like remote_mta and such.
    """
    originals = match_bounce_headers(_Part(message))
    results = {'Content-Description-Parts':
               originals['Content-Description-Parts']}
    score = 0
    del originals['Content-Description-Parts']

    for key in originals:
        score += 1  # score still goes up, even if value doesn't parse
        r = BOUNCE_MATCHERS[key]

        scan = (r.match(v) for v in originals[key])
        matched = [m.groups() for m in scan if m]

        # a key is counted in the score, but only added if it matches
        if len(matched) > 0:
            score += len(matched) // len(originals[key])
            results[key] = matched

    return BounceAnalyzer(results, score / BOUNCE_MAX)


class BounceAnalyzer(object):
    """
    BounceAnalyzer collects up the score and the headers and gives more
    meaningful interaction with them.  You can keep it simple and just use
    is_hard, is_soft, and probable methods to see if there was a bounce.
    If you need more information then attributes are set for each of the following:

        * primary_status -- The main status number that determines hard vs soft.
        * secondary_status -- Advice status.
        * combined_status -- the 2nd and 3rd number combined gives more detail.
        * remote_mta -- The MTA that you sent mail to and aborted.
        * reporting_mta -- The MTA that was sending the mail and has to report to you.
        * diagnostic_codes -- Human readable codes usually with info from the provider.
        * action -- Usually 'failed', and turns out to be not too useful.
        * content_parts -- All the attachments found as a hash keyed by the type.
        * original -- The original message, if it's found.
        * report -- All report elements, as _Part objects.
        * notification -- Usually the detailed reason you bounced.
    """
    def __init__(self, headers, score):
        """
        Initializes all the various attributes you can use to analyze the bounce
        results.
        """
        self.headers = headers
        self.score = score

        if 'Status' in self.headers:
            status = self.headers['Status'][0]
            self.primary_status = int(status[0]), PRIMARY_STATUS_CODES.get(
                    status[0], u'Unknown Status Code {}'.format(status[0]))
            self.secondary_status = int(status[1]), SECONDARY_STATUS_CODES.get(
                    status[1], u'Unknown Subject Code {}'.format(status[1]))
            combined = "".join(status[1:])
            self.combined_status = int(combined), COMBINED_STATUS_CODES.get(
                    combined, COMBINED_STATUS_CODES.get(
                        status[1] + u'0', u'Unknown Status Code {}'.format(combined)))
        else:
            self.primary_status = (None, None)
            self.secondary_status = (None, None)
            self.combined_status = (None, None)

        if 'Remote-Mta' in self.headers:
            self.remote_mta = self.headers['Remote-Mta'][0][1]
        else:
            self.remote_mta = None

        if 'Reporting-Mta' in self.headers:
            self.reporting_mta = self.headers['Reporting-Mta'][0][1]
        else:
            self.reporting_mta = None

        if 'Final-Recipient' in self.headers:
            self.final_recipient = self.headers['Final-Recipient'][0][1]
        else:
            self.final_recipient = None

        if 'Diagnostic-Code' in self.headers:
            self.diagnostic_codes = self.headers['Diagnostic-Code'][0][1:]
        else:
            self.diagnostic_codes = [None, None]

        if 'Action' in self.headers:
            self.action = self.headers['Action'][0][0]
        else:
            self.action = None

        # these are forced lowercase because they're so damn random
        self.content_parts = self.headers['Content-Description-Parts']
        # and of course, this isn't the original original, it's the wrapper
        self.original = self.content_parts.get('undelivered message', None)

        if self.original and self.original.parts:
            self.original = self.original.parts[0]

        self.report = self.content_parts.get('delivery report', None)
        if self.report and self.report.parts:
            self.report = self.report.parts

        self.notification = self.content_parts.get('notification', None)


    def is_hard(self):
        """
        Tells you if this was a hard bounce, which is determined by the message
        being a probably bounce with a primary_status greater than 4.
        """
        status = self.primary_status[0]
        return self.probable() and status is not None and status > 4

    def is_soft(self):
        """Basically the inverse of is_hard()"""
        status = self.primary_status[0]
        return self.probable() and (status is None or status <= 4)

    def probable(self, threshold=0.3):
        """
        Determines if this is probably a bounce based on the score
        probability.  Default threshold is 0.3 which is conservative.
        """
        return self.score > threshold

    def error_for_humans(self):
        """
        Constructs an error from the status codes that you can print to
        a user.
        """
        if self.primary_status[0]:
            return "%s, %s, %s" % (self.primary_status[1],
                                   self.secondary_status[1],
                                   self.combined_status[1])
        else:
            return "No status codes found in bounce message."
