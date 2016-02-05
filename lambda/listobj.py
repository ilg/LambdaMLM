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

batch_size = 20

list_properties = [
        'name',
        'members',
        'reply-to-list',
        'subject-tag',
        'open-subscription',
        'closed-unsubscription',
        ]

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

class List (object):
    def __init__(self, address=None, username=None, host=None):
        if address is None:
            if username is None or host is None:
                raise TypeError('Either address or username and host must be provided.')
            self.username = username
            self.host = host
            self.address = '{}@{}'.format(name, host)
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
                    Body=yaml.dump(self._config, default_flow_style=False),
                    )
        except Exception as e:
            #print(e)
            #print('Error getting object {} from bucket {}. Make sure they exist and your bucket is in the same region as this function.'.format(self.key, config.config_bucket))
            raise e

    def member_with_address(self, address):
        return next(( m for m in self.members if m.address == address ), None)

    def address_will_modify_address(self, from_address, target_address):
        if from_address != target_address:
            member = self.member_with_address(from_address)
            if MemberFlag.admin not in member.flags and MemberFlag.superadmin not in member.flags:
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

    def addresses_to_receive_from(self, from_address):
        return [
                m.address
                for m in self.members
                if (
                    MemberFlag.diagnostic not in m.flags
                    and MemberFlag.vacation not in m.flags
                    and (
                        MemberFlag.echoPost in m.flags
                        or from_address != m.address
                        )
                    )
                ]

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

        # Make the list be the sender of the email.
        del msg['Sender']
        msg['Sender'] = Header(self.display_address)
        # Capture bounces, etc., to the list address.  # TODO: this isn't quite right, is it?
        del msg['Return-path']
        msg['Return-path'] = Header(self.display_address)  # TODO: VERP?

        # See if replies should default to the list.
        if self.reply_to_list:
            msg['Reply-to'] = Header(self.display_address)

        # See if the list has a subject tag.
        if self.subject_tag:
            prefix = u'[{}] '.format(self.subject_tag)
            subject = msg_get_header(msg, 'Subject')
            if prefix not in subject:
                del msg['Subject']
                msg['Subject'] = Header(u'{}{}'.format(prefix, subject))

        # TODO: body footer
        recipients = self.addresses_to_receive_from(from_address)
        while recipients:
            batch = recipients[:batch_size]
            recipients = recipients[batch_size:]
            print('> Sending to users {}.'.format(batch))
            send(self.address, batch, msg)
            
    @classmethod
    def lists_for_addresses(cls, addresses):
        for a in addresses:
            try:
                yield cls(a)
            except ValueError:
                continue
