#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json

from fabric.utils import puts

import boto3
from botocore.exceptions import ClientError

from .check_config import check_config

__all__ = []

iam = boto3.resource('iam')

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
