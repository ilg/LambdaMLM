#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json

from fabric.utils import puts

import boto3
from botocore.exceptions import ClientError

from .check_config import check_config

__all__ = []

s3 = boto3.resource('s3')

def create_s3_bucket_if_needed(config=None):
    if not config:
        config = check_config()
    try:
        bucket = s3.Bucket(config.s3_bucket)
        puts('S3 bucket already exists (created {}).'.format(bucket.creation_date.isoformat()))
    except ClientError:
        puts('Creating S3 bucket...')
        bucket = s3.create_bucket(
                Bucket=config.s3_bucket,
                CreateBucketConfiguration=dict(
                    LocationConstraint=config.lambda_region,
                    ),
                )
    return bucket
