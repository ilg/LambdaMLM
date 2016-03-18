#!/usr/bin/env python
# -*- coding: utf-8 -*-

import imp
import json
import os
import pprint
pp = pprint.PrettyPrinter(indent=4)

from fabric.api import *
from fabric.utils import puts, error

import boto3
from botocore.exceptions import ClientError

iam = boto3.resource('iam')

basepath = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
codedir = os.path.join(basepath, 'lambda')
libdir = os.path.join(basepath, '.env/lib/python2.7/site-packages')
zipfile = os.path.join(basepath, 'lambda.zip')

def get_lambda_client(config):
    return boto3.client('lambda', region_name=config.lambda_region)

def make_zip():
    with lcd(codedir):
        local('zip --recurse-paths "{zipfile}" * --exclude "*.pyc"'.format(zipfile=zipfile))
    with lcd(libdir):
        local('zip --recurse-paths "{zipfile}" * --exclude "*.pyc" "boto*" "pip*" "docutils*" "setuptools*" "wheel*" "pkg_resources*" "*.dist-info/*"'.format(zipfile=zipfile))

def remove_zip():
    local('rm "{zipfile}"'.format(zipfile=zipfile))

def update_lambda():
    config = check_config()
    make_zip()
    with open(zipfile) as z:
        pp.pprint(get_lambda_client(config).update_function_code(
            ZipFile=z.read(),
            FunctionName=config.lambda_name,
            ))
    remove_zip()

def setup_virtualenv():
    with lcd(basepath):
        local('''
            virtualenv --no-site-packages --distribute .env \
                    && source .env/bin/activate \
                    && pip install -r requirements.txt
            '''.format(
                basepath=basepath,
                ))

def check_config():
    try:
        config = imp.load_source('config', os.path.join(codedir, 'config.py'))
    except IOError:
        error('config.py not found.  Did you create it by copying config.example.py?')
    try:
        config_example = imp.load_source('config_example', os.path.join(codedir, 'config.example.py'))
    except IOError:
        error('config.example.py not found.  Did you remove it?')
    if config.signing_key == config_example.signing_key:
        error('You need to change the signing key to your own unique text.')
    if config.s3_bucket == config_example.s3_bucket:
        error('You need to change the s3 bucket name to a bucket you control.')
    puts('Your config.py appears to be set up.')
    return config

def create_iam_role_if_needed(config=None):
    if not config:
        config = check_config()
    try:
        role = iam.Role(config.iam_role_name)
        puts('IAM role already exists (created {}).'.format(role.create_date.isoformat()))
    except ClientError:
        puts('Creating IAM role...')
        role = iam.create_role(
                RoleName=config.iam_role_name,
                AssumeRolePolicyDocument='''{
                      "Version": "2012-10-17",
                      "Statement": [
                        {
                          "Effect": "Allow",
                          "Principal": {
                            "Service": "lambda.amazonaws.com"
                          },
                          "Action": "sts:AssumeRole"
                        }
                      ]
                    }''',
                )
    puts('Creating/updating role policy...')
    role_policy = role.Policy(config.iam_role_name)
    role_policy.put(
            PolicyDocument=json.dumps({
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": [
                            "logs:CreateLogGroup",
                            "logs:CreateLogStream",
                            "logs:PutLogEvents",
                            ],
                        "Resource": "arn:aws:logs:*:*:*",
                        },
                    {
                        "Effect": "Allow",
                        "Action": [
                            "s3:GetLifecycleConfiguration",
                            ],
                        "Resource": [
                            "arn:aws:s3:::{s3_bucket}".format(s3_bucket=config.s3_bucket),
                            ],
                        },
                    {
                        "Effect": "Allow",
                        "Action": [
                            "s3:PutObject",
                            "s3:GetObject",
                            "s3:DeleteObject",
                            ],
                        "Resource": [
                            "arn:aws:s3:::{s3_bucket}/*".format(s3_bucket=config.s3_bucket),
                            ],
                        },
                    {
                        "Effect": "Allow",
                        "Action": [
                            "SES:SendEmail",
                            "SES:SendRawEmail",
                            ],
                        "Resource": [
                            "arn:aws:ses:*:*:identity/*",
                            ],
                        },
                    ],
                }),
            )
    return role

def create_lambda_if_needed():
    config = check_config()
    client = get_lambda_client(config)
    role = create_iam_role_if_needed(config=config)
    try:
        fn = client.get_function(FunctionName=config.lambda_name)
        puts('Lambda function already exists (last modified {}).'.format(fn.get('Configuration', {}).get('LastModified')))
    except ClientError as e:
        if e.response['Error']['Code'] != 'ResourceNotFoundException':
            raise
        make_zip()
        with open(zipfile) as z:
            client.create_function(
                    FunctionName=config.lambda_name,
                    Runtime='python2.7',
                    Role=role.arn,
                    Handler='lambda.lambda_handler',
                    Code=dict(
                        ZipFile=z.read(),
                        ),
                    Timeout=10,
                    )
        remove_zip()
        puts('Lambda function created.')
