from __future__ import print_function

import copy

import yaml
from enum import Enum

import re

host_regex = re.compile(r'^(([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])\.)*([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9\-]*[A-Za-z0-9])$')
name_regex = re.compile(r'^[a-z0-9-]+$')

import boto3

s3 = boto3.client('s3')
ses = boto3.client('ses')

from botocore.exceptions import ClientError

import email
import email.policy
from email.header import Header
from email.utils import parseaddr, formataddr
from email.mime.multipart import MIMEMultipart
from email.mime.message import MIMEMessage
from email.mime.text import MIMEText
from sestools import msg_get_header
from email_utils import detect_bounce, bounce_defaults

import settings
import control
import templates
from list_member import ListMember, MemberFlag
from list_member_container import ListMemberContainer
from list_exceptions import (
        AlreadySubscribed, ClosedSubscription, ClosedUnsubscription,
        NotSubscribed, UnknownFlag, UnknownOption, ModeratedMessageNotFound,
        InsufficientPermissions, UnknownList)

list_properties = [
        'name',
        'members',
        'subject-tag',
        'bounce-score-threshold',
        'bounce-weights',
        'bounce-decay-factor',
        'reply-to-list',
        'open-subscription',
        'closed-unsubscription',
        'moderated',
        'reject-from-non-members',
        'allow-from-non-members',
        'cc-lists',
        ]
list_properties_protected = [
        'members',
        'cc-lists',
        ]

class _SendPolicy(email.policy.Compat32):
    """How messages are written when they're sent or stored.

    Like the default compat32 policy, except that a header that's already
    folded, or short enough not to need folding, is written exactly as it is.
    The default re-wraps every long header, which would rewrite the trace
    headers of every post.  Lines end in CRLF, the canonical form for email
    and the form SES stores incoming mail in.
    """
    def _fold(self, name, value, sanitize):
        if isinstance(value, str) and not any(u'\udc80' <= c <= u'\udcff' for c in value):
            lines = re.split(r'\r?\n', value)
            if len(lines) > 1 or len(name) + 2 + len(value) <= self.max_line_length:
                return '{}: {}{}'.format(name, self.linesep.join(lines), self.linesep)
        return super(_SendPolicy, self)._fold(name, value, sanitize)


SEND_POLICY = _SendPolicy(linesep='\r\n')


def address_from_user(user):
    _, address = parseaddr(user)
    return address.lower()

class List (ListMemberContainer):
    def __init__(self, address=None, username=None, host=None):
        if address is None:
            if username is None or host is None:
                raise TypeError('Either address or username and host must be provided.')
            self.username = username.lower()
            self.host = host.lower()
            self.address = '{}@{}'.format(self.username, self.host)
        elif '@' not in address:
            raise ValueError('A list address must contain @.')
        else:
            self.address = address.lower()
            (self.username, self.host) = self.address.split('@', 1)
        if not name_regex.match(self.username):
            raise ValueError('Invalid list username.')
        if not host_regex.match(self.host):
            raise ValueError('Invalid list host.')
        self._s3_key = '{}{}/{}.yaml'.format(settings.s3_configuration_prefix, self.host, self.username)
        self._s3_moderation_prefix = '{}{}/{}/'.format(settings.s3_moderation_prefix, self.host, self.username)
        try:
            config_response = s3.get_object(Bucket=settings.s3_bucket, Key=self._s3_key)
        except ClientError:
            raise UnknownList
        self._config = yaml.safe_load(config_response['Body'])
        if self.name:
            self.display_address = u'{} <{}>'.format(self.name, self.address)
        else:
            self.display_address = self.address
        # Default bounce scoring constants
        if not self.bounce_score_threshold:
            self.bounce_score_threshold = getattr(settings, 'bounce_score_threshold', bounce_defaults.bounce_score_threshold)
        if not self.bounce_weights:
            self.bounce_weights = getattr(settings, 'bounce_weights', bounce_defaults.bounce_weights)
        if not self.bounce_decay_factor:
            self.bounce_decay_factor = getattr(settings, 'bounce_decay_factor', bounce_defaults.bounce_decay_factor)

    def __getattr__(self, name):
        prop = name.replace('_', '-')
        if prop not in list_properties:
            raise AttributeError(name)
        return self._config.get(prop)

    def __setattr__(self, name, value):
        if name in list_properties:
            prop = name.replace('_', '-')
            self._config[prop] = value
            return
        super(List, self).__setattr__(name, value)

    def dict(self):
        d = {p: getattr(self, p) for p in list_properties}
        d['members'] = [m.dict() for m in self.members]
        # Bounce weights set in a config file are keyed by ResponseType; use
        # the names, since enum keys serialize differently across versions.
        if d['bounce-weights']:
            d['bounce-weights'] = {getattr(k, 'name', k): v for k, v in d['bounce-weights'].items()}
        return d

    def update_from_dict(self, d):
        if 'members' in d:
            raise KeyError
        for k, v in d.items():
            if k not in list_properties:
                continue
            setattr(self, k, v)
        self._save()

    def _save(self):
        response = s3.put_object(
                Bucket=settings.s3_bucket,
                Key=self._s3_key,
                Body=yaml.safe_dump(self._config, default_flow_style=False, allow_unicode=True),
                )

    def user_subscribe_user(self, from_user, target_user):
        from_address = address_from_user(from_user)
        target_address = address_from_user(target_user)
        self.address_will_modify_address(from_address, target_address)
        if from_address == target_address and not self.open_subscription:
            # List doesn't allow self-subscription.
            raise ClosedSubscription
        self.add_member(target_user)

    def user_unsubscribe_user(self, from_user, target_user):
        from_address = address_from_user(from_user)
        target_address = address_from_user(target_user)
        self.address_will_modify_address(from_address, target_address)
        if from_address == target_address and self.closed_unsubscription:
            # List doesn't allow self-unsubscription.
            raise ClosedUnsubscription
        member = self.member_with_address(target_address)
        self.remove_member(member)

    def user_own_flags(self, user):
        address = address_from_user(user)
        member = self.member_with_address(address)
        if not member:
            raise NotSubscribed
        if MemberFlag.admin in member.flags:
            all_flags = MemberFlag
        else:
            all_flags = MemberFlag.userlevel_flags()
        return [(f, f in member.flags) for f in all_flags]

    def user_set_member_flag_value(self, from_user, target_user, flag_name, value):
        from_address = address_from_user(from_user)
        target_address = address_from_user(target_user)
        self.address_will_modify_address(from_address, target_address)
        member = self.member_with_address(target_address)
        if not member:
            raise NotSubscribed
        try:
            flag = MemberFlag[flag_name]
        except KeyError:
            raise UnknownFlag
        # The superAdmin flag cannot be modified by email command.
        if flag == MemberFlag.superAdmin:
            raise InsufficientPermissions
        if flag not in MemberFlag.userlevel_flags() and MemberFlag.admin not in self.member_with_address(from_address).flags:
            raise InsufficientPermissions
        if value:
            member.flags.add(flag)
        else:
            try:
                member.flags.remove(flag)
            except KeyError:
                # Trying to remove an element from the set that isn't in the set raises KeyError.  Ignore it.
                pass
        self._save()

    def user_config_values(self, from_user):
        from_address = address_from_user(from_user)
        member = self.member_with_address(from_address)
        if not member or MemberFlag.admin not in member.flags:
            raise InsufficientPermissions
        return [(o, getattr(self, o)) for o in list_properties if o not in list_properties_protected]

    def user_set_config_value(self, from_user, option, value):
        from_address = address_from_user(from_user)
        member = self.member_with_address(from_address)
        if not member or MemberFlag.admin not in member.flags:
            raise InsufficientPermissions
        if option not in list_properties or option in list_properties_protected:
            raise UnknownOption
        setattr(self, option, value)
        self._save()

    def user_get_members(self, from_user):
        from_address = address_from_user(from_user)
        member = self.member_with_address(from_address)
        # TODO: allow non-admins to view list membership?
        if not member or MemberFlag.admin not in member.flags:
            raise InsufficientPermissions
        return [
                '{}: {}'.format(m.address, ', '.join(f.name for f in m.flags))
                for m in self.members
                ]

    def update_member_from_dict(self, member, d):
        member.update_from_dict(d)
        self._save()

    def invite(self, target_address, command, verb):
        command_address = '{}@{}'.format(settings.command_user, self.host)
        from datetime import timedelta
        validity_duration = timedelta(days=3)  # TODO: make this duration configurable
        token = control.sign(target_address, self.address, validity_duration=validity_duration)
        cmd = 'list {} {} "{}"'.format(self.address, command, token)
        list_name = self.name
        if not list_name:
            list_name = self.address
        control.send_response(
                source=command_address,
                destination=target_address,
                subject='Invitation to {} {} - Fwd: {}'.format(
                    verb,
                    list_name,
                    control.sign(cmd, target_address, validity_duration=validity_duration),
                    ),
                body='To accept the invitation, reply to this email.  You can leave the body of the reply blank.',
                )

    def invite_subscribe_member(self, target_address):
        if self.member_with_address(target_address):
            # Address is already subscribed.
            raise AlreadySubscribed
        self.invite(target_address, 'accept_subscription_invitation', 'join')

    def invite_unsubscribe_member(self, target_member):
        if not target_member:
            raise NotSubscribed
        self.invite(target_member.address, 'accept_unsubscription_invitation', 'leave')

    def accept_invitation(self, from_user, token, action):
        from_address = address_from_user(from_user)
        token_address = control.get_signed_command(token, self.address)
        if token_address.lower() != from_address:
            raise control.InvalidSignatureException
        action(from_address)

    def accept_subscription_invitation(self, from_user, token):
        self.accept_invitation(
                from_user,
                token,
                lambda from_address: self.add_member(from_user),
                )

    def accept_unsubscription_invitation(self, from_user, token):
        self.accept_invitation(
                from_user,
                token,
                lambda from_address: self.remove_member(self.member_with_address(from_address)),
                )

    def addresses_to_receive_from(self, from_address):
        return [
                m.address
                for m in self.members
                if m.can_receive_from(from_address)
                ]

    def list_address_with_tags(self, *tags):
        tags = map(lambda s: s.replace('@', '='), tags)
        return '{}+{}@{}'.format(self.username, '+'.join(tags), self.host)

    def verp_address(self, address):
        return self.list_address_with_tags(address, 'bounce')

    def munged_from(self, address):
        return self.list_address_with_tags(address, 'from')

    def address_header(self):
        """The list's address for an address header, with its name if it has one.

        formataddr encodes a non-ASCII name without encoding the address.
        """
        if self.name:
            return formataddr((self.name, self.address))
        return self.address

    @staticmethod
    def msg_replace_header(msg, header, new_value=None):
        # The value exactly as received.  (msg.get() would turn undeclared
        # 8-bit bytes into an encoded word with the charset unknown-8bit.)
        old_value = next((v for k, v in msg.raw_items() if k.lower() == header.lower()), None)
        if old_value:
            msg['X-Original-' + header] = old_value
        del msg[header]
        if new_value:
            msg[header] = new_value

    def send(self, msg, mod_approved=False, cc_chain=()):
        # cc_chain holds the addresses of the lists that cc'd this one, so
        # cc-lists that refer back to each other don't loop forever.
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
        if not mod_approved:
            member = self.member_with_address(from_address)
            if member is None and self.reject_from_non_members:
                print('{} cannot send email to {} (not a member and list rejects email from non-members).'.format(from_address, self.address))
                return
            if member and MemberFlag.noPost in member.flags:
                print('{} cannot send email to {} (noPost is set).'.format(from_address, self.address))
                return
            if member is None and not self.allow_from_non_members:
                print('Moderating message from non-member.')
                self.moderate(msg)
                return
            if member and MemberFlag.modPost in member.flags:
                print('Moderating message because member has modPost set.')
                self.moderate(msg)
                return
            if self.moderated and (
                    member is None
                    or MemberFlag.preapprove not in member.flags):
                print('Moderating message because list is moderated and message is not from a member with preapprove set.')
                self.moderate(msg)
                return

        # Send to CC lists.
        cc_chain = cc_chain + (self.address,)
        for cc_list in List.lists_for_addresses(self.cc_lists):
            if cc_list.address in cc_chain:
                continue
            # send() rewrites the message's headers, so each list gets its own copy.
            cc_list.send(copy.deepcopy(msg), mod_approved=True, cc_chain=cc_chain)

        # Strip out any exising DKIM signature.
        self.msg_replace_header(msg, 'DKIM-Signature')

        # Strip out any existing return path.
        self.msg_replace_header(msg, 'Return-path')

        # Make the list be the sender of the email.
        self.msg_replace_header(msg, 'Sender', self.address_header())

        # Munge the From: header.
        # While munging the From: header probably technically violates an RFC,
        # it does appear to be the current best practice for MLMs:
        # https://dmarc.org/supplemental/mailman-project-mlm-dmarc-reqs.html
        list_name = self.name
        if not list_name:
            list_name = self.address
        self.msg_replace_header(
                msg,
                'From',
                formataddr((
                    '{} (via {})'.format(from_name, list_name),
                    self.munged_from(from_address),
                    )),
                )

        # See if replies should default to the list.
        if self.reply_to_list:
            self.msg_replace_header(msg, 'Reply-to', self.address_header())
            # Cc the sender so replies reach them too, in a single Cc: header
            # that keeps anyone who was already Cc'd.
            existing_cc = [re.sub(r'\r?\n[ \t]', ' ', v) for k, v in msg.raw_items() if k.lower() == 'cc']
            self.msg_replace_header(msg, 'CC', ', '.join(existing_cc + [raw_from]))
        else:
            self.msg_replace_header(msg, 'Reply-to', raw_from)

        # See if the list has a subject tag.
        if self.subject_tag:
            prefix = u'[{}] '.format(self.subject_tag)
            subject = msg_get_header(msg, 'Subject') or u''
            if prefix not in subject:
                self.msg_replace_header(msg, 'Subject', Header(u'{}{}'.format(prefix, subject)))

        # TODO: body footer
        for recipient in self.addresses_to_receive_from(from_address):
            # Set the return-path VERP-style: [list username]+[recipient s/@/=/]+bounce@[host]
            return_path = self.verp_address(recipient)
            if not mod_approved:
                # Suppress printing when mod-approved, because the output will go to the moderator approving it.
                print('> Sending to {}.'.format(recipient))
            ses.send_raw_email(
                    Source=return_path,
                    Destinations=[ recipient, ],
                    RawMessage={ 'Data': msg.as_bytes(policy=SEND_POLICY), },
                    )
            
    @staticmethod
    def moderation_expiration_days(default=3):
        """The number of days after which held messages expire.

        Read from the bucket's lifecycle rule for the moderation prefix, in
        either the older form with a top-level Prefix or the current form
        with a Filter.  Falls back to `default` if there's no such rule.
        """
        try:
            lifecycle = s3.get_bucket_lifecycle_configuration(Bucket=settings.s3_bucket)
        except ClientError as e:
            # Most likely NoSuchLifecycleConfiguration.
            print('Unable to read the bucket lifecycle configuration: {}'.format(e))
            return default
        for rule in lifecycle.get('Rules', []):
            if rule.get('Status', 'Enabled') != 'Enabled':
                continue
            rule_filter = rule.get('Filter') or {}
            prefix = rule.get('Prefix', rule_filter.get('Prefix', (rule_filter.get('And') or {}).get('Prefix')))
            days = (rule.get('Expiration') or {}).get('Days')
            if prefix == settings.s3_moderation_prefix and days:
                return days
        return default

    def moderate(self, msg):
        # For some reason, this import doesn't work at the file level.
        from control import sign
        message_id = msg['message-id']
        if not message_id:
            print('Unable to moderate incoming message due to lack of Message-ID: header.')
            raise ValueError('Messages must contain a Message-ID: header.')
        message_id = message_id.replace(':', '_')  # Make it safe for subject-command.
        # Put the email message into the list's moderation holding space on S3.
        response = s3.put_object(
                Bucket=settings.s3_bucket,
                Key=self._s3_moderation_prefix + message_id,
                Body=msg.as_bytes(policy=SEND_POLICY),
                )
        # Get the moderation auto-deletion/auto-rejection interval from the S3 bucket lifecycle configuration.
        from datetime import timedelta
        mod_interval = timedelta(days=self.moderation_expiration_days())
        # Wrap the moderated message for inclusion in the notification to mods.
        forward_mime = MIMEMessage(msg)
        control_address = '{}@{}'.format(settings.command_user, self.host)
        for moderator in self.moderator_addresses:
            # Build up the notification email per-moderator so that we can include
            # pre-signed moderation commands specific to that moderator.
            approve_cmd = sign('list {} mod approve "{}"'.format(self.address, message_id), moderator, mod_interval)
            reject_cmd = sign('list {} mod reject "{}"'.format(self.address, message_id), moderator, mod_interval)
            message = MIMEMultipart()
            message['Subject'] = 'Message to {} needs approval: {}'.format(self.address, approve_cmd)
            message['From'] = control_address
            message['To'] = moderator
            message.attach(MIMEText(templates.render(
                'notify_moderators.jinja2',
                list_name=self.address,
                control_address=control_address,
                approve_command=approve_cmd,
                reject_command=reject_cmd,
                moderation_days=mod_interval.days
                )))
            message.attach(forward_mime)
            ses.send_raw_email(
                    Source=control_address,
                    Destinations=[ moderator, ],
                    RawMessage={ 'Data': message.as_bytes(policy=SEND_POLICY), },
                    )

    def _user_mod_act_on(self, from_user, message_id, action):
        from_address = address_from_user(from_user)
        member = self.member_with_address(from_address)
        if member is None or MemberFlag.moderator not in member.flags:
            raise InsufficientPermissions
        try:
            return action(
                    Bucket=settings.s3_bucket,
                    Key=self._s3_moderation_prefix + message_id,
                    )
        except ClientError:
            raise ModeratedMessageNotFound

    def user_mod_approve(self, from_user, message_id):
        response = self._user_mod_act_on(from_user, message_id, s3.get_object)
        self.send(email.message_from_bytes(response['Body'].read()), mod_approved=True)
        self._user_mod_act_on(from_user, message_id, s3.delete_object)

    def user_mod_reject(self, from_user, message_id):
        # Head the object first, since delete won't raise an exception if the object doesn't exist.
        self._user_mod_act_on(from_user, message_id, s3.head_object)
        self._user_mod_act_on(from_user, message_id, s3.delete_object)

    @classmethod
    def lists_for_addresses(cls, addresses):
        try:
            for a in addresses:
                try:
                    yield cls(a)
                except (ValueError, UnknownList):
                    # Not a list address, or no such list.
                    continue
        except TypeError:
            return

    @classmethod
    def handle_bounce_to(cls, bounce_address, msg):
        print('Handling bounce to {}.'.format(bounce_address))
        if '@' not in bounce_address:
            raise ValueError('Bounced-to addresses must contain an @.')
        username, host = bounce_address.split('@', 1)
        if '+' not in bounce_address:
            raise ValueError('Bounced-to username must contain a +.')
        list_username, _ = username.split('+', 1)
        l = cls(username=list_username, host=host)
        if not l:
            raise ValueError('Bounced-to address does not resolve to a known list.')
        print('Bounce received for list {}.'.format(l.display_address))
        member = l.member_passing_test(lambda m: l.verp_address(m.address).lower() == bounce_address.lower())
        if not member:
            print('No member found matching the bounce address.')
            return
        member.add_response(detect_bounce(msg))
        score = member.bounce_score(weights=l.bounce_weights, decay=l.bounce_decay_factor)
        print('New bounce score for {} is {}.'.format(member.address, score))
        if score > l.bounce_score_threshold:
            print('Score exceeds bounce score threshold, so flagging the member as bouncing.')
            member.flags.add(MemberFlag.bouncing)
        l._save()
        # TODO: send email to member and/or admin(s) noting that the bounce threshold has been reached?
        
