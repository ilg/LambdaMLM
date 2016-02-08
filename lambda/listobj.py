from __future__ import print_function

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
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.message import MIMEMessage
from email.mime.text import MIMEText
import email.utils
from sestools import msg_get_header

import config
from list_member import ListMember, MemberFlag

if hasattr(config, 'smtp_server'):
    import smtplib
    smtp = smtplib.SMTP_SSL(config.smtp_server)
    if hasattr(config, 'smtp_user') and hasattr(config, 'smtp_password'):
        smtp.login(config.smtp_user, config.smtp_password)
    def send(source, destinations, message):
        smtp.sendmail(source, destinations, message.as_string())
else:
    # Sending using SES doesn't seem to work because of validation issues...
    def send(source, destinations, message):
        ses.send_raw_email(
                Source=source,
                Destinations=destinations,
                RawMessage={ 'Data': message.as_string(), },
                )

list_properties = [
        'name',
        'members',
        'subject-tag',
        'bounce-limit',
        'reply-to-list',
        'open-subscription',
        'closed-unsubscription',
        'moderated',
        'reject-from-non-members',
        ]
list_properties_protected = [
        'members',
        ]

default_bounce_limit = 5

class InsufficientPermissions(Exception):
    pass

class AlreadySubscribed(Exception):
    pass

class NotSubscribed(Exception):
    pass

class ClosedSubscription(Exception):
    pass

class ClosedUnsubscription(Exception):
    pass

class UnknownFlag(Exception):
    pass

class UnknownOption(Exception):
    pass

class ModeratedMessageNotFound(Exception):
    pass

class List (object):
    def __init__(self, address=None, username=None, host=None):
        if address is None:
            if username is None or host is None:
                raise TypeError('Either address or username and host must be provided.')
            self.username = username
            self.host = host
            self.address = '{}@{}'.format(username, host)
        elif '@' not in address:
            raise ValueError('A list address must contain @.')
        else:
            self.address = address
            (self.username, self.host) = address.split('@', 1)
        if not name_regex.match(self.username):
            raise ValueError('Invalid list username.')
        if not host_regex.match(self.host):
            raise ValueError('Invalid list host.')
        self._s3_key = '{}{}/{}.yaml'.format(config.s3_configuration_prefix, self.host, self.username)
        self._s3_moderation_prefix = '{}{}/{}/'.format(config.s3_moderation_prefix, self.host, self.username)
        config_response = s3.get_object(Bucket=config.s3_bucket, Key=self._s3_key)
        self._config = yaml.safe_load(config_response['Body'])
        if self.name:
            self.display_address = u'{} <{}>'.format(self.name, self.address)
        else:
            self.display_address = self.address
        # Default bounce limit.
        if not self.bounce_limit:
            self.bounce_limit = default_bounce_limit

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

    def _save(self):
        response = s3.put_object(
                Bucket=config.s3_bucket,
                Key=self._s3_key,
                Body=yaml.safe_dump(self._config, default_flow_style=False, allow_unicode=True),
                )

    @property
    def moderator_addresses(self):
        return [
                m.address
                for m in self.members
                if MemberFlag.moderator in m.flags
                ]

    def member_passing_test(self, test):
        return next(( m for m in self.members if test(m) ), None)

    def member_with_address(self, address):
        return self.member_passing_test(lambda m: m.address == address)

    def address_will_modify_address(self, from_address, target_address):
        if from_address != target_address:
            from_member = self.member_with_address(from_address)
            # Only admin members can modify other members.
            if MemberFlag.admin not in from_member.flags:
                raise InsufficientPermissions
            target_member = self.member_with_address(target_address)
            # Only superAdmin members can modify admin members.
            if MemberFlag.admin in target_member.flags and MemberFlag.superAdmin not in from_member.flags:
                raise InsufficientPermissions

    def user_subscribe_user(self, from_user, target_user):
        _, from_address = email.utils.parseaddr(from_user)
        _, target_address = email.utils.parseaddr(target_user)
        self.address_will_modify_address(from_address, target_address)
        if self.member_with_address(target_address):
            # Address is already subscribed.
            raise AlreadySubscribed
        if from_address == target_address and not self.open_subscription:
            # List doesn't allow self-subscription.
            raise ClosedSubscription
        self.members.append(ListMember(target_address))
        # TODO: store human-readable name?
        self._save()

    def user_unsubscribe_user(self, from_user, target_user):
        _, from_address = email.utils.parseaddr(from_user)
        _, target_address = email.utils.parseaddr(target_user)
        self.address_will_modify_address(from_address, target_address)
        member = self.member_with_address(target_address)
        if not member:
            raise NotSubscribed
        if from_address == target_address and self.closed_unsubscription:
            # List doesn't allow self-unsubscription.
            raise ClosedUnsubscription
        self.members.remove(member)
        self._save()

    def user_own_flags(self, user):
        _, address = email.utils.parseaddr(user)
        member = self.member_with_address(address)
        if not member:
            raise NotSubscribed
        if MemberFlag.admin in member.flags:
            all_flags = MemberFlag
        else:
            all_flags = MemberFlag.userlevel_flags()
        return [(f, f in member.flags) for f in all_flags]

    def user_set_member_flag_value(self, from_user, target_user, flag_name, value):
        _, from_address = email.utils.parseaddr(from_user)
        _, target_address = email.utils.parseaddr(target_user)
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
        _, from_address = email.utils.parseaddr(from_user)
        member = self.member_with_address(from_address)
        if not member or MemberFlag.admin not in member.flags:
            raise InsufficientPermissions
        return [(o, getattr(self, o)) for o in list_properties if o not in list_properties_protected]

    def user_set_config_value(self, from_user, option, value):
        _, from_address = email.utils.parseaddr(from_user)
        member = self.member_with_address(from_address)
        if not member or MemberFlag.admin not in member.flags:
            raise InsufficientPermissions
        if option not in list_properties or option in list_properties_protected:
            raise UnknownOption
        setattr(self, option, value)
        self._save()

    def user_get_members(self, from_user):
        _, from_address = email.utils.parseaddr(from_user)
        member = self.member_with_address(from_address)
        # TODO: allow non-admins to view list membership?
        if not member or MemberFlag.admin not in member.flags:
            raise InsufficientPermissions
        return [
                '{}: {}'.format(m.address, ', '.join(f.name for f in m.flags))
                for m in self.members
                ]

    def addresses_to_receive_from(self, from_address):
        return [
                m.address
                for m in self.members
                if (
                    MemberFlag.vacation not in m.flags
                    and (
                        MemberFlag.echoPost in m.flags
                        or from_address != m.address
                        )
                    and m.bounce_count <= self.bounce_limit
                    )
                ]

    def list_address_with_tags(self, *tags):
        tags = map(lambda s: s.replace('@', '='), tags)
        return '{}+{}@{}'.format(self.username, '+'.join(tags), self.host)

    def verp_address(self, address):
        return self.list_address_with_tags(address, 'bounce')

    def send(self, msg, mod_approved=False):
        _, from_address = email.utils.parseaddr(msg_get_header(msg, 'From'))
        if not mod_approved:
            member = self.member_with_address(from_address)
            if member is None and self.reject_from_non_members:
                print('{} cannot send email to {} (not a member and list rejects email from non-members).'.format(from_address, self.address))
                return
            if member and MemberFlag.noPost in member.flags:
                print('{} cannot send email to {} (noPost is set).'.format(from_address, self.address))
                return
            if (member is None
                    or MemberFlag.modPost in member.flags
                    or (self.moderated and MemberFlag.preapprove not in member.flags)
                    ):
                print('Moderating message.')
                self.moderate(msg)
                return

        # Strip out any exising DKIM signature.
        del msg['DKIM-Signature']

        # Strip out any existing return path.
        del msg['Return-path']

        # Make the list be the sender of the email.
        del msg['Sender']
        msg['Sender'] = Header(self.display_address)

        # See if replies should default to the list.
        if self.reply_to_list:
            del msg['Reply-to']
            msg['Reply-to'] = Header(self.display_address)

        # See if the list has a subject tag.
        if self.subject_tag:
            prefix = u'[{}] '.format(self.subject_tag)
            subject = msg_get_header(msg, 'Subject')
            if prefix not in subject:
                del msg['Subject']
                msg['Subject'] = Header(u'{}{}'.format(prefix, subject))

        # TODO: body footer
        for recipient in self.addresses_to_receive_from(from_address):
            # Set the return-path VERP-style: [list username]+[recipient s/@/=/]+bounce@[host]
            return_path = self.verp_address(recipient)
            if not mod_approved:
                # Suppress printing when mod-approved, because the output will go to the moderator approving it.
                print('> Sending to {}.'.format(recipient))
            send(return_path, [ recipient, ], msg)
            
    def moderate(self, msg):
        # For some reason, this import doesn't work at the file level.
        from control import sign
        message_id = msg['message-id']
        if not message_id:
            print('Unable to moderate incoming message due to lack of Message-ID: header.')
            raise ValueError('Messages must contain a Message-ID: header.')
        message_id = message_id.replace(':', '_')  # Make it safe for subject-command.
        response = s3.put_object(
                Bucket=config.s3_bucket,
                Key=self._s3_moderation_prefix + message_id,
                Body=msg.as_string(),
                )
        control_address = 'lambda@{}'.format(self.host)
        # TODO: figure out the mod interval by using get_bucket_lifecycle_configuration to introspect the moderation queue's expiration interval?  Or, conversely, set the bucket's lifecycle configuration based on a list setting of the expiration interval?
        from datetime import timedelta
        mod_interval = timedelta(days=4)
        forward_mime = MIMEMessage(msg)
        for moderator in self.moderator_addresses:
            approve_cmd = sign('list {} mod approve "{}"'.format(self.address, message_id), moderator, mod_interval)
            reject_cmd = sign('list {} mod reject "{}"'.format(self.address, message_id), moderator, mod_interval)
            message = MIMEMultipart()
            message['Subject'] = 'Message to {} needs approval: {}'.format(self.address, approve_cmd)
            message['From'] = control_address
            message['To'] = moderator
            message.attach(MIMEText(
                '''The included message needs moderator approval to be posted to {}.

To approve this message, reply to this email or send an email to {} with subject:

        {}

To reject this message, send an email to {} with subject:

        {}

If no action has been taken in {} days, the message will be automatically rejected.

'''.format(self.address, control_address, approve_cmd, control_address, reject_cmd, mod_interval.days)
                ))
            message.attach(forward_mime)
            ses.send_raw_email(
                    Source=control_address,
                    Destinations=[ moderator, ],
                    RawMessage={ 'Data': message.as_string(), },
                    )

    def _user_mod_act_on(self, from_user, message_id, action):
        _, from_address = email.utils.parseaddr(from_user)
        member = self.member_with_address(from_address)
        if member is None or MemberFlag.moderator not in member.flags:
            raise InsufficientPermissions
        try:
            return action(
                    Bucket=config.s3_bucket,
                    Key=self._s3_moderation_prefix + message_id,
                    )
        except ClientError:
            raise ModeratedMessageNotFound

    def user_mod_approve(self, from_user, message_id):
        response = self._user_mod_act_on(from_user, message_id, s3.get_object)
        self.send(email.message_from_file(response['Body']), mod_approved=True)
        self._user_mod_act_on(from_user, message_id, s3.delete_object)

    def user_mod_reject(self, from_user, message_id):
        # Head the object first, since delete won't raise an exception if the object doesn't exist.
        self._user_mod_act_on(from_user, message_id, s3.head_object)
        self._user_mod_act_on(from_user, message_id, s3.delete_object)

    @classmethod
    def lists_for_addresses(cls, addresses):
        for a in addresses:
            try:
                yield cls(a)
            except ValueError:
                continue

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
        member = l.member_passing_test(lambda m: l.verp_address(m.address) == bounce_address)
        if not member:
            print('No member found matching the bounce address.')
            return
        member.bounce_count += 1
        print('Incremented bounce count for {} to {}.'.format(member.address, member.bounce_count))
        l._save()
        # TODO: send email to member and/or admin(s) noting that the bounce limit has been reached?
        
