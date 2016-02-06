from __future__ import print_function

import yaml
from enum import Enum

import re

host_regex = re.compile(r'^(([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])\.)*([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9\-]*[A-Za-z0-9])$')
name_regex = re.compile(r'^[a-z0-9-]+$')

import boto3

s3 = boto3.client('s3')

from email.header import Header
import email.utils
from sestools import msg_get_header

from list_member import ListMember, MemberFlag

import config
if hasattr(config, 'smtp_server'):
    import smtplib
    smtp = smtplib.SMTP_SSL(config.smtp_server)
    if hasattr(config, 'smtp_user') and hasattr(config, 'smtp_password'):
        smtp.login(config.smtp_user, config.smtp_password)
    def send(source, destinations, message):
        smtp.sendmail(source, destinations, message.as_string())
else:
    # Sending using SES doesn't seem to work because of validation issues...
    ses = boto3.client('ses')
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
        self.key = '{}/{}.yaml'.format(self.host, self.username)
        try:
            config_response = s3.get_object(Bucket=config.config_bucket, Key=self.key)
        except Exception as e:
            #print(e)
            #print('Error getting object {} from bucket {}. Make sure they exist and your bucket is in the same region as this function.'.format(self.key, config.config_bucket))
            raise e
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
        try:
            response = s3.put_object(
                    Bucket=config.config_bucket,
                    Key=self.key,
                    Body=yaml.safe_dump(self._config, default_flow_style=False, allow_unicode=True),
                    )
        except Exception as e:
            #print(e)
            #print('Error getting object {} from bucket {}. Make sure they exist and your bucket is in the same region as this function.'.format(self.key, config.config_bucket))
            raise e

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

    def send(self, msg):
        _, from_address = email.utils.parseaddr(msg_get_header(msg, 'From'))
        member = self.member_with_address(from_address)
        if member is None:
            # TODO: allow a list to receive from off-list; allow off-list emails to go to moderation
            print('{} cannot send email to {} (not a member).'.format(from_address, self.address))
            return
        if MemberFlag.noPost in member.flags:
            print('{} cannot send email to {} (noPost is set).'.format(from_address, self.address))
            return
        if MemberFlag.modPost in member.flags:
            print('Email from {} to {} should be moderated (not yet implemented).'.format(from_address, self.address))
            return
        # TODO: check if the list is moderated

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
            print('> Sending to {}.'.format(recipient))
            send(return_path, [ recipient, ], msg)
            
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
        
