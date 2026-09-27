#!/usr/bin/env python3
"""Real mailboxes for LambdaMLM's end-to-end tests, over IMAP and SMTP.

The accounts are listed in ~/.config/lambdamlm-test/mailboxes.ini (override
with LAMBDAMLM_MAILBOXES), one section per account; see that file for the keys.
They must be used only for testing: fetched messages are deleted.  Passwords
are never printed.

    python3 -m e2e.mailboxes check      # log in to each account, sending nothing
"""

import configparser
import email
import email.policy
import imaplib
import os
import smtplib
import ssl
import sys
import time

CONFIG_PATH = os.environ.get(
        'LAMBDAMLM_MAILBOXES', os.path.expanduser('~/.config/lambdamlm-test/mailboxes.ini'))
TIMEOUT = 30


class Mailbox(object):
    def __init__(self, name, section):
        self.name = name
        self.address = section['address']
        self.username = section.get('username') or self.address
        self._password = section['password']
        self.imap_host = section['imap_host']
        self.imap_port = section.getint('imap_port', 993)
        self.smtp_host = section['smtp_host']
        self.smtp_port = section.getint('smtp_port', 465)

    def __repr__(self):
        return 'Mailbox({!r}, {!r})'.format(self.name, self.address)

    # -------------------------------------------------------------- IMAP

    def _imap(self):
        imap = imaplib.IMAP4_SSL(self.imap_host, self.imap_port,
                                 ssl_context=ssl.create_default_context(), timeout=TIMEOUT)
        imap.login(self.username, self._password)
        return imap

    def message_count(self):
        imap = self._imap()
        try:
            _, data = imap.select('INBOX', readonly=True)
            return int(data[0])
        finally:
            imap.logout()

    def fetch(self, delete=True, folders=('INBOX',)):
        """Return the raw bytes of every message in the given folders.

        Deletes them afterwards unless delete is False.
        """
        messages = []
        imap = self._imap()
        try:
            for folder in folders:
                typ, _ = imap.select(_quote(folder), readonly=not delete)
                if typ != 'OK':
                    continue
                _, data = imap.search(None, 'ALL')
                ids = data[0].split()
                for num in ids:
                    _, parts = imap.fetch(num, '(RFC822)')
                    messages.append(parts[0][1])
                if delete and ids:
                    imap.store(b','.join(ids), '+FLAGS', '\\Deleted')
                    imap.expunge()
        finally:
            imap.logout()
        return messages

    def wait_for(self, predicate, timeout=300, interval=15, folders=('INBOX',)):
        """Poll until messages matching predicate(raw_bytes) arrive; return them.

        Matching messages are deleted; others are left alone.
        """
        deadline = time.time() + timeout
        while True:
            found = []
            imap = self._imap()
            try:
                for folder in folders:
                    typ, _ = imap.select(_quote(folder))
                    if typ != 'OK':
                        continue
                    _, data = imap.search(None, 'ALL')
                    for num in data[0].split():
                        _, parts = imap.fetch(num, '(RFC822)')
                        raw = parts[0][1]
                        if predicate(raw):
                            found.append(raw)
                            imap.store(num, '+FLAGS', '\\Deleted')
                    imap.expunge()
            finally:
                imap.logout()
            if found or time.time() >= deadline:
                return found
            time.sleep(interval)

    # -------------------------------------------------------------- SMTP

    def _smtp(self):
        context = ssl.create_default_context()
        if self.smtp_port == 465:
            smtp = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=context, timeout=TIMEOUT)
        else:
            smtp = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=TIMEOUT)
            smtp.starttls(context=context)
        smtp.login(self.username, self._password)
        return smtp

    def check_smtp(self):
        self._smtp().quit()

    def send(self, message, to_addrs):
        """Send an email.message.Message (or raw bytes) to the given addresses."""
        smtp = self._smtp()
        try:
            if isinstance(message, bytes):
                smtp.sendmail(self.address, to_addrs, message)
            else:
                smtp.send_message(message, from_addr=self.address, to_addrs=to_addrs)
        finally:
            smtp.quit()


def _quote(folder):
    return '"{}"'.format(folder) if ' ' in folder else folder


def load(path=CONFIG_PATH, include_disabled=False):
    config = configparser.ConfigParser(interpolation=None)
    if not config.read(path):
        raise SystemExit('No mailbox file at {}.'.format(path))
    return [Mailbox(name, config[name]) for name in config.sections()
            if include_disabled or config[name].getboolean('enabled', True)]


def parse(raw):
    return email.message_from_bytes(raw, policy=email.policy.default)


def check(mailboxes):
    ok = True
    for mailbox in mailboxes:
        results = []
        try:
            results.append('IMAP ok ({} in INBOX)'.format(mailbox.message_count()))
        except Exception as e:
            ok = False
            results.append('IMAP FAILED: {}: {}'.format(type(e).__name__, str(e)[:150]))
        try:
            mailbox.check_smtp()
            results.append('SMTP ok')
        except Exception as e:
            ok = False
            results.append('SMTP FAILED: {}: {}'.format(type(e).__name__, str(e)[:150]))
        print('{}: {}'.format(mailbox.name, '; '.join(results)))
    return ok


def main(args):
    if args[:1] == ['check']:
        sys.exit(0 if check(load()) else 1)
    sys.exit(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])
