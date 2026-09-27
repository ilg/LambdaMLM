"""Compare two end-to-end runs, scenario by scenario.

    scripts/e2e compare ENV/LABEL ENV/LABEL

For example, `scripts/e2e compare staging/py2-baseline staging/py3`.  For each
scenario it shows how many copies each recipient got in each run, the
differences between the delivered messages' main headers and text bodies
(with each run's token normalized away), other recorded results (moderation
notices, command output, bounce entries, API results) and the number of error
lines in the function's logs.
"""

import email
import email.policy
import glob
import json
import os
import re
import sys

from e2e.run import RESULTS_DIR

HEADERS = ('From', 'Sender', 'Reply-To', 'To', 'CC', 'Subject', 'X-Original-From', 'X-Original-Sender')
SUMMARY_KEYS = ('notices', 'confirmations', 'outputs', 'bounce_entries', 'api', 'steps')
ERROR = re.compile(r'Traceback|Error|Task timed out|Process exited')


def load(run):
    directory = os.path.join(RESULTS_DIR, run)
    scenarios = {}
    for path in sorted(glob.glob(os.path.join(directory, '*', 'summary.json'))):
        with open(path) as f:
            summary = json.load(f)
        scenarios[summary['scenario']] = (os.path.dirname(path), summary)
    return scenarios


def label(address):
    local, _, domain = address.partition('@')
    return address if local.startswith('e2e-') else '<{}>'.format(domain)


def message(directory, recipient, token):
    paths = sorted(glob.glob(os.path.join(directory, '{}.*.eml'.format(recipient))))
    if not paths:
        return None
    with open(paths[0], 'rb') as f:
        msg = email.message_from_bytes(f.read(), policy=email.policy.default)
    def norm(value):
        return re.sub(r'\s+', ' ', str(value).replace(token, '<token>')).strip()
    headers = {h: norm(msg[h]) for h in HEADERS if msg[h] is not None}
    body = msg.get_body(preferencelist=('plain',))
    text = norm(body.get_content()) if body is not None else None
    return headers, text


def compare(old_run, new_run):
    old, new = load(old_run), load(new_run)
    for scenario in sorted(set(old) | set(new), key=lambda s: (s not in old, s)):
        print('== {}'.format(scenario))
        if scenario not in old or scenario not in new:
            print('   only in {}'.format(old_run if scenario in old else new_run))
            continue
        (old_dir, a), (new_dir, b) = old[scenario], new[scenario]
        recipients = sorted(set(a.get('deliveries', {})) | set(b.get('deliveries', {})))
        for r in recipients:
            before, after = a.get('deliveries', {}).get(r, 0), b.get('deliveries', {}).get(r, 0)
            expected = b.get('expected', a.get('expected', {})).get(r)
            marker = '' if before == after else '   <-- changed'
            print('   {:44} {} -> {} (expected {}){}'.format(label(r), before, after, expected, marker))
            if before and after:
                m1, m2 = message(old_dir, r, a['token']), message(new_dir, r, b['token'])
                if m1 and m2:
                    for h in HEADERS:
                        if m1[0].get(h) != m2[0].get(h):
                            print('      {}: {!r}\n      {}  -> {!r}'.format(
                                    h, mask(m1[0].get(h)), ' ' * len(h), mask(m2[0].get(h))))
                    if m1[1] != m2[1]:
                        print('      body differs')
        for key in SUMMARY_KEYS:
            if key in a or key in b:
                va, vb = a.get(key), b.get(key)
                if key == 'api':
                    va = va and (va['payload'].get('StatusCode') or va['payload'].get('errorType'))
                    vb = vb and (vb['payload'].get('StatusCode') or vb['payload'].get('errorType'))
                print('   {}: {} -> {}'.format(key, mask(va), mask(vb)))
        errors_a = sum(1 for line in a.get('logs', []) if ERROR.search(line))
        errors_b = sum(1 for line in b.get('logs', []) if ERROR.search(line))
        print('   error lines in logs: {} -> {}'.format(errors_a, errors_b))


def mask(value):
    """Hide the real mailboxes' addresses, as label() does."""
    if value is None:
        return None
    return re.sub(r'[\w.+-]+@[\w-]+(\.[\w-]+)+', lambda m: label(m.group(0)), str(value))


def main(args):
    if len(args) != 2:
        sys.exit(__doc__)
    compare(*args)
