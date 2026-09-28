"""Moderation: holding a post, notifying the list's moderators, and approving or rejecting it."""

import email
from datetime import timedelta
from email.mime.message import MIMEMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import mail
import settings
import signing
import storage
import templates
from list_exceptions import InsufficientPermissions
from list_member import MemberFlag
from listobj import address_from_user
from mail import SEND_POLICY


def moderate(mlist, msg):
    message_id = msg['message-id']
    if not message_id:
        print('Unable to moderate incoming message due to lack of Message-ID: header.')
        raise ValueError('Messages must contain a Message-ID: header.')
    message_id = message_id.replace(':', '_')  # Make it safe for subject-command.
    # Put the email message into the list's moderation holding space on S3.
    storage.hold_message(mlist.host, mlist.username, message_id, msg.as_bytes(policy=SEND_POLICY))
    # Get the moderation auto-deletion/auto-rejection interval from the S3 bucket lifecycle configuration.
    mod_interval = timedelta(days=storage.moderation_expiration_days())
    # Wrap the moderated message for inclusion in the notification to mods.
    forward_mime = MIMEMessage(msg)
    control_address = '{}@{}'.format(settings.command_user, mlist.host)
    for moderator in mlist.moderator_addresses:
        # Build up the notification email per-moderator so that we can include
        # pre-signed moderation commands specific to that moderator.
        approve_cmd = signing.sign('list {} mod approve "{}"'.format(mlist.address, message_id), moderator, mod_interval)
        reject_cmd = signing.sign('list {} mod reject "{}"'.format(mlist.address, message_id), moderator, mod_interval)
        message = MIMEMultipart()
        message['Subject'] = 'Message to {} needs approval: {}'.format(mlist.address, approve_cmd)
        message['From'] = control_address
        message['To'] = moderator
        message.attach(MIMEText(templates.render(
            'notify_moderators.jinja2',
            list_name=mlist.address,
            control_address=control_address,
            approve_command=approve_cmd,
            reject_command=reject_cmd,
            moderation_days=mod_interval.days
            )))
        message.attach(forward_mime)
        mail.send_raw(control_address, moderator, message.as_bytes(policy=SEND_POLICY))


def require_moderator(mlist, from_user):
    member = mlist.member_with_address(address_from_user(from_user))
    if member is None or MemberFlag.moderator not in member.flags:
        raise InsufficientPermissions


def approve(mlist, from_user, message_id):
    """Send a held post to the list, then delete it."""
    require_moderator(mlist, from_user)
    data = storage.held_message(mlist.host, mlist.username, message_id)
    mlist.send(email.message_from_bytes(data), mod_approved=True)
    storage.delete_held_message(mlist.host, mlist.username, message_id)


def reject(mlist, from_user, message_id):
    """Delete a held post."""
    require_moderator(mlist, from_user)
    # Check first, since deleting doesn't report a missing message.
    storage.check_held_message(mlist.host, mlist.username, message_id)
    storage.delete_held_message(mlist.host, mlist.username, message_id)
