"""Run end-to-end scenarios against a deployment and save what happens.

    scripts/e2e run <env> <label> [scenario ...]
    scripts/e2e run <env> --list

Each scenario sends real mail (through SES from the test inboxes, or through
the real mailboxes' SMTP servers), waits for what arrives at every test
inbox and mailbox, and saves the raw messages, a summary and the function's
log lines under ~/.cache/lambdamlm-test/results/<env>/<label>/<scenario>/.
Results stay out of the repo because they contain the real addresses.

Runs with different labels (the old code's baseline, then the new code) can be
compared with `scripts/e2e compare`.
"""

import datetime
import email
import email.policy
import json
import os
import sys
import time
import uuid
from email.message import EmailMessage

from e2e import environment, mailboxes, ses_inbox

RESULTS_DIR = os.path.expanduser('~/.cache/lambdamlm-test/results')
WAIT = 150        # seconds to wait for mail that should arrive
QUIET_WAIT = 90   # seconds to watch for mail when none should arrive
GRACE = 30        # seconds to keep watching for strays once the expected mail is in


class Context(object):
    def __init__(self, env, label, scenario):
        self.env = env
        self.real = mailboxes.load()
        self.scenario = scenario
        self.token = uuid.uuid4().hex[:10]
        self.started = time.time()
        self.directory = os.path.join(RESULTS_DIR, env.name, label, scenario)
        os.makedirs(self.directory, exist_ok=True)
        self.notes = []
        self.summary = {'scenario': scenario, 'token': self.token,
                        'started': datetime.datetime.utcnow().isoformat() + 'Z'}

    # Addresses
    @property
    def inbox1(self):
        return self.env.inboxes[0]

    @property
    def inbox2(self):
        return self.env.inboxes[1]

    @property
    def idn_inbox(self):
        return next(a for a in self.env.inboxes if '@xn--' in a or '.xn--' in a)

    def list_address(self, name, host=None):
        return '{}@{}'.format(name, host or self.inbox1.split('@', 1)[1])

    def command_address(self, host=None):
        return 'lambda@{}'.format(host or self.inbox1.split('@', 1)[1])

    def mailbox(self, domain):
        return next(m for m in self.real if m.address.endswith('@' + domain))

    # Sending
    def message(self, sender, to, subject='', body=None, **headers):
        msg = EmailMessage()
        msg['From'] = sender
        msg['To'] = to
        msg['Subject'] = subject or 'E2E {} {}'.format(self.scenario, self.token)
        msg['X-E2E-Token'] = self.token
        for name, value in headers.items():
            msg[name.replace('_', '-')] = value
        msg.set_content(body or 'End-to-end test {} ({}).\n'.format(self.scenario, self.token))
        return msg

    def send_ses(self, message, destinations, source=None):
        """Send through SES.  message may be an EmailMessage or raw bytes."""
        raw = message if isinstance(message, bytes) else message.as_bytes()
        try:
            response = self.env.client('sesv2').send_email(
                    FromEmailAddress=source or _address(message),
                    Destination={'ToAddresses': list(destinations)},
                    Content={'Raw': {'Data': raw}})
            self.note('sent through SES to {}: {}'.format(destinations, response['MessageId']))
            return True
        except Exception as e:
            self.note('SES refused to send: {}: {}'.format(type(e).__name__, e))
            return False

    def send_smtp(self, mailbox, message, destinations):
        mailbox.send(message, list(destinations))
        self.note('sent from {} over SMTP to {}'.format(mailbox.name, destinations))

    # Receiving
    def matches(self, raw, token=None):
        return (token or self.token).encode('ascii') in raw

    def collect(self, recipients, expected=None, timeout=WAIT, token=None, keep=True):
        """Wait for mail with the token at each recipient; save and return it.

        Stops once every expected recipient has mail and GRACE seconds more have
        passed (to catch duplicates and strays), or at the timeout.  With no
        expected recipients, it watches for QUIET_WAIT seconds.
        """
        expected = set(expected or ())
        deadline = time.time() + (timeout if expected else QUIET_WAIT)
        settled = None
        found = {r: [] for r in recipients}
        while True:
            for r in recipients:
                if r in self.env.inboxes:
                    # Reading an S3 inbox leaves its messages there, so this is all of them.
                    found[r] = self._fetch(r, token)
                else:
                    # Fetching from a real mailbox deletes what it returns.
                    found[r] = found[r] + self._fetch(r, token)
            if settled is None and all(found[r] for r in expected):
                settled = time.time()
            if time.time() >= deadline or (settled is not None and time.time() - settled >= GRACE):
                break
            time.sleep(10)
        if keep:
            for recipient, messages in found.items():
                for n, raw in enumerate(messages):
                    with open(os.path.join(self.directory, '{}.{}.eml'.format(recipient, n)), 'wb') as f:
                        f.write(raw)
        return found

    def _fetch(self, recipient, token):
        if recipient in self.env.inboxes:
            return [raw for _, _, raw in ses_inbox.messages(self.env, recipient, self.started - 5)
                    if self.matches(raw, token)]
        mailbox = next(m for m in self.real if m.address == recipient)
        return mailbox.wait_for(lambda raw: self.matches(raw, token), timeout=0,
                                folders=mailbox_folders(mailbox))

    def expect(self, delivered, received):
        """Record which recipients got how many copies, against expectations."""
        counts = {r: len(m) for r, m in received.items()}
        self.summary.setdefault('deliveries', {}).update(counts)
        self.summary.setdefault('expected', {}).update({r: (1 if r in delivered else 0) for r in received})
        return counts

    def note(self, text):
        self.notes.append(text)
        print('    ' + text)

    def finish(self):
        self.summary['notes'] = self.notes
        self.summary['logs'] = self.logs()
        with open(os.path.join(self.directory, 'summary.json'), 'w') as f:
            json.dump(self.summary, f, indent=2, sort_keys=True)

    def logs(self):
        """The deployed function's log lines since the scenario started."""
        if not self.env.function:
            return []
        logs = self.env.client('logs')
        group = '/aws/lambda/{}'.format(self.env.function)
        lines = []
        try:
            paginator = logs.get_paginator('filter_log_events')
            for page in paginator.paginate(logGroupName=group, startTime=int((self.started - 5) * 1000)):
                lines.extend(e['message'].rstrip('\n') for e in page['events'])
        except Exception as e:
            lines.append('(could not read logs: {})'.format(e))
        return lines


def mailbox_folders(mailbox):
    """INBOX and the account's spam folder, found by its \\Junk special-use flag."""
    if not hasattr(mailbox, '_folders'):
        folders = ['INBOX']
        try:
            imap = mailbox._imap()
            _, listing = imap.list()
            imap.logout()
            for line in listing:
                text = line.decode('utf-8', 'replace')
                if '\\Junk' in text or '\\Spam' in text:
                    folders.append(text.rsplit(' "/" ', 1)[-1].strip().strip('"'))
        except Exception:
            pass
        mailbox._folders = tuple(folders)
    return mailbox._folders


def _address(message):
    from email.utils import parseaddr
    return parseaddr(message['From'])[1]


def list_members(ctx, list_name, host=None):
    """The test list's members, from the deployment's bucket."""
    s3 = ctx.env.client('s3')
    host = host or ctx.inbox1.split('@', 1)[1]
    body = s3.get_object(Bucket=ctx.env.list_bucket,
                         Key='config/{}/{}.yaml'.format(host, list_name))['Body'].read().decode('utf-8')
    return [line.split(':', 1)[1].strip() for line in body.splitlines() if line.startswith('  address:')]


def all_recipients(ctx):
    return list(ctx.env.inboxes) + [m.address for m in ctx.real]


# ---------------------------------------------------------------- scenarios

SCENARIOS = []


def scenario(function):
    SCENARIOS.append(function)
    return function


def _post(ctx, sender, list_address, send):
    members = list_members(ctx, *list_address.split('@'))
    expected = [m for m in members if m.lower() != sender.lower()]
    send()
    received = ctx.collect(all_recipients(ctx), expected)
    ctx.expect(expected, received)
    return received


@scenario
def post_ses(ctx):
    """A member posts through SES."""
    to = ctx.list_address('e2e-test')
    _post(ctx, ctx.inbox2, to, lambda: ctx.send_ses(ctx.message(ctx.inbox2, to), [to]))


@scenario
def post_gmail(ctx):
    """A member posts from Gmail, so the list relays a DKIM-signed Gmail message."""
    sender = ctx.mailbox('gmail.com')
    to = ctx.list_address('e2e-test')
    _post(ctx, sender.address, to,
          lambda: ctx.send_smtp(sender, ctx.message(sender.address, to), [to]))


@scenario
def post_gmx(ctx):
    """A member posts from GMX."""
    sender = ctx.mailbox('gmx.com')
    to = ctx.list_address('e2e-test')
    _post(ctx, sender.address, to,
          lambda: ctx.send_smtp(sender, ctx.message(sender.address, to), [to]))


@scenario
def post_idn(ctx):
    """A post to the list on the internationalized (λ) domain."""
    host = ctx.idn_inbox.split('@', 1)[1]
    to = ctx.list_address('e2e-test', host)
    _post(ctx, ctx.idn_inbox, to, lambda: ctx.send_ses(ctx.message(ctx.idn_inbox, to), [to]))


@scenario
def post_non_ascii_name(ctx):
    """A member whose display name isn't ASCII (an encoded word)."""
    to = ctx.list_address('e2e-test')
    msg = ctx.message('Jörg E2E <{}>'.format(ctx.inbox2), to,
                      subject='E2E post_non_ascii_name été {}'.format(ctx.token))
    _post(ctx, ctx.inbox2, to, lambda: ctx.send_ses(msg, [to], source=ctx.inbox2))


@scenario
def post_eight_bit_header(ctx):
    """A member's message with raw 8-bit bytes in its From header (no encoded word)."""
    to = ctx.list_address('e2e-test')
    raw = ('From: Jörg E2E <{}>\r\nTo: {}\r\nSubject: E2E post_eight_bit_header {}\r\n'
           'X-E2E-Token: {}\r\nMIME-Version: 1.0\r\nContent-Type: text/plain; charset=utf-8\r\n'
           'Content-Transfer-Encoding: 8bit\r\n\r\nCafé {}\r\n').format(
               ctx.inbox2, to, ctx.token, ctx.token, ctx.token).encode('utf-8')
    _post(ctx, ctx.inbox2, to, lambda: ctx.send_ses(raw, [to], source=ctx.inbox2))


@scenario
def post_bcc(ctx):
    """A member Bccs the list: it's in the envelope but not the headers."""
    to = ctx.list_address('e2e-test')
    msg = ctx.message(ctx.inbox2, 'undisclosed-recipients:;')
    _post(ctx, ctx.inbox2, to, lambda: ctx.send_ses(msg, [to], source=ctx.inbox2))


@scenario
def post_large(ctx):
    """A member posts a message with a 5 MB attachment."""
    to = ctx.list_address('e2e-test')
    msg = ctx.message(ctx.inbox2, to)
    msg.add_attachment(os.urandom(5 * 1024 * 1024), maintype='application',
                       subtype='octet-stream', filename='e2e-5mb.bin')
    _post(ctx, ctx.inbox2, to, lambda: ctx.send_ses(msg, [to]))


@scenario
def mail_to_non_list(ctx):
    """Mail to an address on the list domain that isn't a list."""
    to = 'e2e-nobody@' + ctx.inbox1.split('@', 1)[1]
    ctx.send_ses(ctx.message(ctx.inbox2, to), [to])
    received = ctx.collect(all_recipients(ctx))
    ctx.expect([], received)


@scenario
def moderation(ctx):
    """A non-member posts; the moderator gets a notice and approves by reply."""
    to = ctx.list_address('e2e-test')
    ctx.send_ses(ctx.message(ctx.idn_inbox, to), [to])
    notices = ctx.collect([ctx.inbox1], [ctx.inbox1])[ctx.inbox1]
    ctx.summary['notices'] = len(notices)
    if not notices:
        ctx.note('no moderation notice arrived')
        return
    notice = email.message_from_bytes(notices[0], policy=email.policy.default)
    ctx.note('notice subject: ' + str(notice['Subject']))
    reply = ctx.message(ctx.inbox1, str(notice['From']), subject='Re: ' + str(notice['Subject']))
    ctx.started = time.time()
    ctx.send_ses(reply, [str(notice['Reply-To'] or notice['From'])], source=ctx.inbox1)
    members = list_members(ctx, 'e2e-test')
    received = ctx.collect(all_recipients(ctx), members)
    ctx.expect(members, received)


@scenario
def command_members(ctx):
    """An admin runs `members` by email: signed reply, then the output."""
    command = 'list {} members'.format(ctx.list_address('e2e-test'))
    ctx.send_ses(ctx.message(ctx.inbox1, ctx.command_address(), subject=command), [ctx.command_address()])
    replies = ctx.collect([ctx.inbox1], [ctx.inbox1], token=command.split()[1])[ctx.inbox1]
    confirmations = [r for r in replies if b'please reply' in r.lower() or b'reply to this email' in r.lower()]
    ctx.summary['confirmations'] = len(confirmations)
    if not confirmations:
        ctx.note('no confirmation request arrived')
        return
    request = email.message_from_bytes(confirmations[-1], policy=email.policy.default)
    ctx.note('confirmation subject: ' + str(request['Subject']))
    ctx.started = time.time()
    reply = ctx.message(ctx.inbox1, ctx.command_address(), subject='Re: ' + str(request['Subject']))
    ctx.send_ses(reply, [ctx.command_address()])
    outputs = ctx.collect([ctx.inbox1], [ctx.inbox1], token='Output of')[ctx.inbox1]
    ctx.summary['outputs'] = len(outputs)


@scenario
def bounce_and_complaint(ctx):
    """A post to SES's bounce and complaint simulators; the bounce is recorded."""
    to = ctx.list_address('e2e-bounces')
    ctx.send_ses(ctx.message(ctx.inbox2, to), [to])
    time.sleep(QUIET_WAIT)
    s3 = ctx.env.client('s3')
    body = s3.get_object(Bucket=ctx.env.list_bucket,
                         Key='config/{}/e2e-bounces.yaml'.format(to.split('@', 1)[1]))['Body'].read()
    with open(os.path.join(ctx.directory, 'e2e-bounces.yaml'), 'wb') as f:
        f.write(body)
    ctx.summary['bounce_entries'] = body.count(b'!bouncekind')
    ctx.note('list now has {} bounce entries'.format(ctx.summary['bounce_entries']))


@scenario
def api_get_list(ctx):
    """The direct-invoke API's GetList."""
    response = ctx.env.client('lambda').invoke(
            FunctionName=ctx.env.function,
            Payload=json.dumps({'Action': 'GetList', 'ListAddress': ctx.list_address('e2e-test')}))
    payload = json.loads(response['Payload'].read())
    ctx.summary['api'] = {'status': response['StatusCode'], 'error': response.get('FunctionError'),
                          'payload': payload}
    ctx.note('GetList returned {}'.format(payload.get('StatusCode') if isinstance(payload, dict) else payload))


def display(ctx, address):
    """An address for printing: SES inboxes in full, real mailboxes by provider."""
    if address in ctx.env.inboxes:
        return address
    return '<{}>'.format(address.split('@', 1)[1])


def main(args):
    if not args:
        sys.exit(__doc__)
    env = environment.load(args[0])
    if args[1:2] == ['--list']:
        for s in SCENARIOS:
            print('{:24} {}'.format(s.__name__, s.__doc__.strip()))
        return
    if len(args) < 2:
        sys.exit(__doc__)
    label = args[1]
    wanted = args[2:] or [s.__name__ for s in SCENARIOS]
    unknown = set(wanted) - {s.__name__ for s in SCENARIOS}
    if unknown:
        sys.exit('Unknown scenarios: {}'.format(', '.join(sorted(unknown))))
    for s in SCENARIOS:
        if s.__name__ not in wanted:
            continue
        print('{}: {}'.format(s.__name__, s.__doc__.strip()))
        ctx = Context(env, label, s.__name__)
        try:
            s(ctx)
        except Exception as e:
            ctx.note('scenario failed: {}: {}'.format(type(e).__name__, e))
        ctx.finish()
        if 'deliveries' in ctx.summary:
            got, want = ctx.summary['deliveries'], ctx.summary['expected']
            print('    deliveries: ' + ', '.join(
                    '{}={}{}'.format(display(ctx, r), got[r], '' if got[r] == want[r] else ' (expected {})'.format(want[r]))
                    for r in sorted(got)))
    print('Results in {}'.format(os.path.join(RESULTS_DIR, env.name, label)))
