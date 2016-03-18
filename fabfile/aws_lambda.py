#!/usr/bin/env python
# -*- coding: utf-8 -*-

import pprint
pp = pprint.PrettyPrinter(indent=4)

from fabric.api import *
from fabric.utils import puts

import boto3
from botocore.exceptions import ClientError

from .check_config import check_config
from .aws_iam import create_iam_role_if_needed
from .aws_s3 import create_s3_bucket_if_needed
from .paths import zipfile, codedir, libdir

__all__ = []

def get_lambda_client(config):
    return boto3.client('lambda', region_name=config.lambda_region)

def make_zip():
    with lcd(codedir):
        local('zip --recurse-paths "{zipfile}" * --exclude "*.pyc"'.format(zipfile=zipfile))
    with lcd(libdir):
        local('zip --recurse-paths "{zipfile}" * --exclude "*.pyc" "boto*" "pip*" "docutils*" "setuptools*" "wheel*" "pkg_resources*" "*.dist-info/*"'.format(zipfile=zipfile))

def remove_zip():
    local('rm "{zipfile}"'.format(zipfile=zipfile))

@task
def update_lambda():
    config = check_config()
    make_zip()
    with open(zipfile) as z:
        pp.pprint(get_lambda_client(config).update_function_code(
            ZipFile=z.read(),
            FunctionName=config.lambda_name,
            ))
    remove_zip()

@task
def create_lambda():
    config = check_config()
    create_s3_bucket_if_needed(config)
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
