"""Test lists in a deployment's bucket, whose members are the test inboxes and mailboxes.

    scripts/e2e lists setup <env> [--apply]
    scripts/e2e lists teardown <env> [--apply]

Setup and teardown only print what they would do unless given --apply.  They
only ever touch lists whose names start with "e2e-", and setup never replaces
an existing list.

The YAML is written by hand in the layout the code itself writes (sorted keys,
!Member and !flag tags), so both the old Python 2 code and the new code read it.
"""

import sys

from botocore.exceptions import ClientError

from e2e import mailboxes

LIST_PREFIX = 'e2e-'


def _member(address, name=None, flags=()):
    lines = ['- !Member', '  address: {}'.format(address)]
    if flags:
        lines.append('  flags: !!set')
        lines.extend("    !flag '{}': null".format(f) for f in flags)
    else:
        lines.append('  flags: !!set {}')
    if name:
        lines.append('  name: {}'.format(name))
    return lines


def _config(members, **options):
    lines = []
    for key in sorted(list(options) + ['members']):
        if key == 'members':
            lines.append('members:')
            for member in members:
                lines.extend(_member(*member))
        else:
            value = options[key]
            if isinstance(value, bool):
                value = 'true' if value else 'false'
            lines.append('{}: {}'.format(key, value))
    return ('\n'.join(lines) + '\n').encode('utf-8')


def planned_lists(env, real_mailboxes):
    """{(host, list name): YAML bytes} for the environment's test lists."""
    inboxes = env.inboxes
    admin = inboxes[0]
    hosts = []
    for address in inboxes:
        host = address.split('@', 1)[1]
        if host not in hosts:
            hosts.append(host)
    real = [(m.address, None, ()) for m in real_mailboxes]
    lists = {}
    for host in hosts:
        host_inboxes = [a for a in inboxes if a.endswith('@' + host)]
        members = ([(host_inboxes[0], 'E2E Admin', ('admin', 'moderator'))]
                   + [(a, None, ()) for a in host_inboxes[1:]]
                   + [(admin, 'E2E Admin', ('admin', 'moderator'))] * (host_inboxes[0] != admin)
                   + real)
        # Lists on an internationalized domain get a non-ASCII name too (issue #9).
        suffix = u' \u03bb' if host.startswith('xn--') or '.xn--' in host else ''
        # A plain list.
        lists[(host, LIST_PREFIX + 'test')] = _config(
                members, name='E2E Test' + suffix, **{'subject-tag': 'E2E', 'allow-from-non-members': False})
        # A moderated list, with reply-to-list for the Cc handling.
        lists[(host, LIST_PREFIX + 'moderated')] = _config(
                members, name='E2E Moderated' + suffix, moderated=True,
                **{'subject-tag': 'E2E-M', 'reply-to-list': True})
    # A list whose members are SES's bounce and complaint simulators.
    lists[(hosts[0], LIST_PREFIX + 'bounces')] = _config(
            [(admin, 'E2E Admin', ('admin',)),
             ('bounce@simulator.amazonses.com', None, ()),
             ('complaint@simulator.amazonses.com', None, ())],
            name='E2E Bounces', **{'allow-from-non-members': True})
    # A list the subscription scenarios join and leave, so the other lists'
    # members never change.
    lists[(hosts[0], LIST_PREFIX + 'subscribe')] = _config(
            [(admin, 'E2E Admin', ('admin',))],
            name='E2E Subscribe', **{'open-subscription': True})
    return lists


def key(host, name):
    return 'config/{}/{}.yaml'.format(host, name)


def setup(env, apply):
    s3 = env.client('s3')
    steps = []
    for (host, name), body in sorted(planned_lists(env, mailboxes.load()).items()):
        k = key(host, name)
        try:
            s3.head_object(Bucket=env.list_bucket, Key=k)
            print('{}@{} already exists; leaving it.'.format(name, host))
            continue
        except ClientError:
            pass
        steps.append(('Create list {}@{} (s3://{}/{})'.format(name, host, env.list_bucket, k),
                      lambda k=k, body=body: s3.put_object(Bucket=env.list_bucket, Key=k, Body=body)))
    from e2e.ses_inbox import run_steps
    run_steps(steps, apply)


def teardown(env, apply):
    s3 = env.client('s3')
    steps = []
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=env.list_bucket):
        for obj in page.get('Contents', []):
            parts = obj['Key'].split('/')
            # config/<host>/e2e-*.yaml and moderation/<host>/e2e-*/...
            if len(parts) >= 3 and parts[0] in ('config', 'moderation') and parts[2].startswith(LIST_PREFIX):
                steps.append(('Delete s3://{}/{}'.format(env.list_bucket, obj['Key']),
                              lambda k=obj['Key']: s3.delete_object(Bucket=env.list_bucket, Key=k)))
    from e2e.ses_inbox import run_steps
    run_steps(steps, apply)


def main(args):
    from e2e import environment
    if len(args) < 2 or args[0] not in ('setup', 'teardown'):
        sys.exit(__doc__)
    env = environment.load(args[1])
    (setup if args[0] == 'setup' else teardown)(env, '--apply' in args)
