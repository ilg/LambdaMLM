"""The AWS clients the function uses, each created the first time it's needed.

Creating them lazily keeps importing the app free of side effects, and gives
the tests one place to substitute fakes.  Call them as `aws_clients.s3()`,
never through `from aws_clients import s3`, so a substitute reaches every
caller.
"""

import functools

import boto3


@functools.cache
def s3():
    return boto3.client('s3')


@functools.cache
def ses():
    return boto3.client('ses')


@functools.cache
def ssm():
    return boto3.client('ssm')
