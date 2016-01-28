from __future__ import print_function

import yaml

import re

host_regex = re.compile(r'^(([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])\.)*([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9\-]*[A-Za-z0-9])$')
name_regex = re.compile(r'^[a-z0-9-]+$')

import boto3

s3 = boto3.client('s3')
ses = boto3.client('ses')

from config import config_bucket

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
            config_response = s3.get_object(Bucket=config_bucket, Key=self.key)
        except Exception as e:
            print(e)
            print('Error getting object {} from bucket {}. Make sure they exist and your bucket is in the same region as this function.'.format(self.key, config_bucket))
            raise e
        self.config = yaml.load(config_response['Body'])
        print('Loaded list {} configuration: {}'.format(self.address, self.config))

    def send(self, msg):
        # TODO: check if the list allows messages from this message's sender
        # TODO: check if the list might allow messages from this message's sender with moderator approval

        # Strip out any exising DKIM signature.
        del msg['DKIM-Signature']

        del msg['Sender']
        msg['Sender'] = self.address
        del msg['Return-path']
        msg['Return-path'] = self.address  # TODO: VERP?
        # TODO: subject tagging
        # TODO: body footer
        # TODO (maybe): batch sends
        for user, flags in self.config['users'].iteritems():
            # TODO: skip vacation users, maybe bouncing users
            # TODO: skip sending back to the sender unless echopost is set
            print('> Sending to user {}.'.format(user))
            ses.send_raw_email(
                    Source=self.address,
                    Destinations=[ user, ],
                    RawMessage={ 'Data': msg.as_string(), },
                    )
            
    @classmethod
    def lists_for_addresses(cls, addresses):
        for a in addresses:
            try:
                yield cls(a)
            except ValueError:
                continue
