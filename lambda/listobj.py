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
        ]

CanSend = Enum('CanSend', [
    'no',
    'moderated',
    'yes',
    ])

class List:
    def __init__(self, address=None, name=None, host=None):
        if address is None:
            if name is None or host is None:
                raise TypeError('Either address or name and host must be provided.')
            self.name = name
            self.host = host
            self.address = '{}@{}'.format(name, host)
        elif '@' not in address:
            raise ValueError('A list address must contain @.')
        else:
            self.address = address
            (self.name, self.host) = address.split('@', 1)
        if not name_regex.match(self.name):
            raise ValueError('Invalid list name.')
        if not host_regex.match(self.host):
            raise ValueError('Invalid list host.')
        self.key = '{}/{}.yaml'.format(self.host, self.name)
        try:
            config_response = s3.get_object(Bucket=config.config_bucket, Key=self.key)
        except Exception as e:
            print(e)
            print('Error getting object {} from bucket {}. Make sure they exist and your bucket is in the same region as this function.'.format(self.key, config.config_bucket))
            raise e
        self._config = yaml.safe_load(config_response['Body'])
        for prop in list_properties:
            setattr(self, prop.replace('-', '_'), self._config.get(prop))
        if self.name:
            self.display_address = u'{} <{}>'.format(self.name, self.address)
        else:
            self.display_address = self.address

    def address_can_send(self, address):
        member = next(( m for m in self.members if m.address == address ), None)
        if member is None:
            # TODO: allow a list to receive from off-list; allow off-list emails to go to moderation
            return CanSend.no
        if MemberFlag.noPost in member.flags:
            return CanSend.no
        if MemberFlag.modPost in member.flags:
            return CanSend.moderated
        # TODO: check if the list is moderated
        return CanSend.yes

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
        can_send = self.address_can_send(from_address)
        if can_send == CanSend.no:
            print('{} cannot send email to {}.'.format(from_address, self.address))
            return
        if can_send == CanSend.moderated:
            # TODO: the list allows messages from this message's sender with moderator approval, so handle moderation
            print('Email from {} to {} should be moderated (not yet implemented).'.format(from_address, self.address))
            return

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
