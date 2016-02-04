from __future__ import print_function

import yaml

import re

host_regex = re.compile(r'^(([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])\.)*([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9\-]*[A-Za-z0-9])$')
name_regex = re.compile(r'^[a-z0-9-]+$')

import boto3

s3 = boto3.client('s3')

from email.header import Header

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
        'users',
        'reply-to-list',
        'subject-tag',
        ]

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
        self.config = yaml.load(config_response['Body'])
        for prop in list_properties:
            setattr(self, prop.replace('-', '_'), self.config.get(prop))
        if self.name:
            self.display_address = u'{} <{}>'.format(self.name, self.address)
        else:
            self.display_address = self.address

    def send(self, msg):
        # TODO: check if the list allows messages from this message's sender
        # TODO: check if the list might allow messages from this message's sender with moderator approval

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

        # TODO: body footer
        # TODO (maybe): batch sends
        for user, flags in self.config['users'].iteritems():
            # TODO: skip vacation users, maybe bouncing users
            # TODO: skip sending back to the sender unless echopost is set
            print('> Sending to user {}.'.format(user))
            send(self.address, [ user, ], msg)
            
    @classmethod
    def lists_for_addresses(cls, addresses):
        for a in addresses:
            try:
                yield cls(a)
            except ValueError:
                continue
