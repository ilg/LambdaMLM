from __future__ import print_function

import yaml

import re

host_regex = re.compile(r'^(([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])\.)*([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9\-]*[A-Za-z0-9])$')
name_regex = re.compile(r'^[a-z0-9-]+$')

import boto3

s3 = boto3.client('s3')

from config import config_bucket

class ListConfiguration:
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
            
