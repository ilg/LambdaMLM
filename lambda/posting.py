"""Posting to a list: what happens to a post, rewriting its headers, and delivering it.

send() runs the steps in order:

1. parse_sender() reads the From header.  It comes first: a post without one
   fails here, before anything is held or sent.
2. disposition() decides whether the post is rejected, held for moderation or
   delivered.  Posts a moderator approved skip this.
3. Each of the list's cc-lists gets its own copy.
4. rewrite_headers() makes the list the post's sender.
5. deliver() sends it to each member who should receive it.
"""

import copy
import enum
import re
from collections import namedtuple
from email.header import Header
from email.utils import formataddr, parseaddr

import mail
import moderation
from list_member import MemberFlag
from mail import SEND_POLICY
from sestools import msg_get_header

Sender = namedtuple('Sender', [
    'raw_from',  # the From header exactly as received, unfolded
    'name',      # the display name, or the address's local part
    'address',   # the address, lowercased
    ])


class Disposition(enum.Enum):
    reject = 'reject'
    moderate = 'moderate'
    deliver = 'deliver'


def parse_sender(msg):
    from_user = msg_get_header(msg, 'From')
    # The From header exactly as received, for copying into Reply-to and
    # Cc without decoding and re-encoding it.
    raw_from = next((v for k, v in msg.raw_items() if k.lower() == 'from'), from_user)
    raw_from = re.sub(r'\r?\n[ \t]', ' ', raw_from)
    from_name, from_address = parseaddr(from_user)
    from_address = from_address.lower()
    if not from_name:
        # Use the local part (or the whole address, if it has no @).
        from_name = from_address.split('@', 1)[0]
    return Sender(raw_from, from_name, from_address)


def disposition(mlist, from_address):
    """What happens to a post from this address, and the message to log about it.

    Returns (Disposition, message); the message is None for delivery.
    """
    member = mlist.member_with_address(from_address)
    if member is None and mlist.reject_from_non_members:
        return Disposition.reject, '{} cannot send email to {} (not a member and list rejects email from non-members).'.format(from_address, mlist.address)
    if member and MemberFlag.noPost in member.flags:
        return Disposition.reject, '{} cannot send email to {} (noPost is set).'.format(from_address, mlist.address)
    if member is None and not mlist.allow_from_non_members:
        return Disposition.moderate, 'Moderating message from non-member.'
    if member and MemberFlag.modPost in member.flags:
        return Disposition.moderate, 'Moderating message because member has modPost set.'
    if mlist.moderated and (
            member is None
            or MemberFlag.preapprove not in member.flags):
        return Disposition.moderate, 'Moderating message because list is moderated and message is not from a member with preapprove set.'
    return Disposition.deliver, None


def send(mlist, msg, mod_approved=False, cc_chain=()):
    # cc_chain holds the addresses of the lists that cc'd this one, so
    # cc-lists that refer back to each other don't loop forever.
    sender = parse_sender(msg)
    if not mod_approved:
        action, message = disposition(mlist, sender.address)
        if action is not Disposition.deliver:
            print(message)
            if action is Disposition.moderate:
                moderation.moderate(mlist, msg)
            return

    # Send to CC lists.
    cc_chain = cc_chain + (mlist.address,)
    for cc_list in mlist.lists_for_addresses(mlist.cc_lists):
        if cc_list.address in cc_chain:
            continue
        # send() rewrites the message's headers, so each list gets its own copy.
        send(cc_list, copy.deepcopy(msg), mod_approved=True, cc_chain=cc_chain)

    rewrite_headers(mlist, msg, sender)
    deliver(mlist, msg, sender, mod_approved)


def replace_header(msg, header, new_value=None):
    # The value exactly as received.  (msg.get() would turn undeclared
    # 8-bit bytes into an encoded word with the charset unknown-8bit.)
    old_value = next((v for k, v in msg.raw_items() if k.lower() == header.lower()), None)
    if old_value:
        msg['X-Original-' + header] = old_value
    del msg[header]
    if new_value:
        msg[header] = new_value


def rewrite_headers(mlist, msg, sender):
    """Make the list the post's sender.  Changes msg in place."""
    # Strip out any exising DKIM signature.
    replace_header(msg, 'DKIM-Signature')

    # Strip out any existing return path.
    replace_header(msg, 'Return-path')

    # Make the list be the sender of the email.
    replace_header(msg, 'Sender', mlist.address_header())

    # Munge the From: header.
    # While munging the From: header probably technically violates an RFC,
    # it does appear to be the current best practice for MLMs:
    # https://dmarc.org/supplemental/mailman-project-mlm-dmarc-reqs.html
    list_name = mlist.name
    if not list_name:
        list_name = mlist.address
    replace_header(
            msg,
            'From',
            formataddr((
                '{} (via {})'.format(sender.name, list_name),
                mlist.munged_from(sender.address),
                )),
            )

    # See if replies should default to the list.
    if mlist.reply_to_list:
        replace_header(msg, 'Reply-to', mlist.address_header())
        # Cc the sender so replies reach them too, in a single Cc: header
        # that keeps anyone who was already Cc'd.
        existing_cc = [re.sub(r'\r?\n[ \t]', ' ', v) for k, v in msg.raw_items() if k.lower() == 'cc']
        replace_header(msg, 'CC', ', '.join(existing_cc + [sender.raw_from]))
    else:
        replace_header(msg, 'Reply-to', sender.raw_from)

    # See if the list has a subject tag.
    if mlist.subject_tag:
        prefix = '[{}] '.format(mlist.subject_tag)
        subject = msg_get_header(msg, 'Subject') or ''
        if prefix not in subject:
            replace_header(msg, 'Subject', Header('{}{}'.format(prefix, subject)))


def deliver(mlist, msg, sender, mod_approved):
    # TODO: body footer
    data = None
    for recipient in mlist.addresses_to_receive_from(sender.address):
        # Set the return-path VERP-style: [list username]+[recipient s/@/=/]+bounce@[host]
        return_path = mlist.verp_address(recipient)
        if not mod_approved:
            # Suppress printing when mod-approved, because the output will go to the moderator approving it.
            print('> Sending to {}.'.format(recipient))
        if data is None:
            # The message is the same for every recipient, so it's written out
            # once, when it's first needed.
            data = msg.as_bytes(policy=SEND_POLICY)
        mail.send_raw(return_path, recipient, data)
