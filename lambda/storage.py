"""Everything the function keeps in S3: list configs, held messages and incoming mail.

The key layout is part of the compatibility contract, so it's defined here and
nowhere else:

- config/<host>/<list username>.yaml for each list's config;
- moderation/<host>/<list username>/<key> for messages held for moderation;
- incoming/<SES message ID> for mail as SES stored it.

(The prefixes come from settings.)  Callers get the exceptions they handle, in
the same cases as before: any S3 error loading a config is UnknownList (more
specifically ListNotFound if there's no such config), and any S3 error on a
held message is ModeratedMessageNotFound.

Saving a config is conditional on its ETag, so a save fails with ListChanged
rather than overwriting a change made since the config was loaded.
"""

import yaml
from botocore.exceptions import ClientError

import aws_clients
import settings
from list_exceptions import ListChanged, ListNotFound, ModeratedMessageNotFound, UnknownList


def list_config_key(host, username):
    return '{}{}/{}.yaml'.format(settings.s3_configuration_prefix, host, username)


def moderation_prefix(host, username):
    return '{}{}/{}/'.format(settings.s3_moderation_prefix, host, username)


def incoming_key(message_id):
    return settings.s3_incoming_email_prefix + message_id


# ---------------------------------------------------------------- list configs

def _status(error):
    return error.response.get('ResponseMetadata', {}).get('HTTPStatusCode')


def load_list_config(host, username):
    """The list's parsed config, and the stored object's ETag.

    Raises ListNotFound if there's no such config, and UnknownList for any
    other S3 error.
    """
    try:
        response = aws_clients.s3().get_object(Bucket=settings.s3_bucket, Key=list_config_key(host, username))
    except ClientError as e:
        if _status(e) == 404:
            raise ListNotFound
        raise UnknownList
    return yaml.safe_load(response['Body']), response.get('ETag')


def save_list_config(host, username, config, etag=None):
    """Save the list's config, and return the saved object's ETag.

    With an ETag (as load_list_config returned it), the save is conditional
    on the stored config still having it.  S3 reports a failed condition as
    412, or as 409 if another write was in progress; both raise ListChanged.
    It reports a config deleted in the meantime as 404, which raises
    ListNotFound.  Other S3 errors pass through.
    """
    kwargs = {} if etag is None else {'IfMatch': etag}
    try:
        response = aws_clients.s3().put_object(
                Bucket=settings.s3_bucket,
                Key=list_config_key(host, username),
                Body=yaml.safe_dump(config, default_flow_style=False, allow_unicode=True),
                **kwargs)
    except ClientError as e:
        if etag is not None and _status(e) in (409, 412):
            raise ListChanged
        if etag is not None and _status(e) == 404:
            raise ListNotFound
        raise
    return response.get('ETag')


# ---------------------------------------------------------------- held messages

def hold_message(host, username, key, data):
    aws_clients.s3().put_object(
            Bucket=settings.s3_bucket,
            Key=moderation_prefix(host, username) + key,
            Body=data,
            )


def held_message(host, username, key):
    """The held message's bytes."""
    try:
        response = aws_clients.s3().get_object(Bucket=settings.s3_bucket, Key=moderation_prefix(host, username) + key)
    except ClientError:
        raise ModeratedMessageNotFound
    return response['Body'].read()


def check_held_message(host, username, key):
    """Raise ModeratedMessageNotFound unless the message is held.

    Deleting doesn't report a missing object, so rejecting checks first.
    """
    try:
        aws_clients.s3().head_object(Bucket=settings.s3_bucket, Key=moderation_prefix(host, username) + key)
    except ClientError:
        raise ModeratedMessageNotFound


def delete_held_message(host, username, key):
    try:
        aws_clients.s3().delete_object(Bucket=settings.s3_bucket, Key=moderation_prefix(host, username) + key)
    except ClientError:
        raise ModeratedMessageNotFound


def moderation_expiration_days(default=3):
    """The number of days after which held messages expire.

    Read from the bucket's lifecycle rule for the moderation prefix, in
    either the older form with a top-level Prefix or the current form
    with a Filter.  Falls back to `default` if there's no such rule.
    """
    try:
        lifecycle = aws_clients.s3().get_bucket_lifecycle_configuration(Bucket=settings.s3_bucket)
    except ClientError as e:
        # Most likely NoSuchLifecycleConfiguration.
        print('Unable to read the bucket lifecycle configuration: {}'.format(e))
        return default
    for rule in lifecycle.get('Rules', []):
        if rule.get('Status', 'Enabled') != 'Enabled':
            continue
        rule_filter = rule.get('Filter') or {}
        prefix = rule.get('Prefix', rule_filter.get('Prefix', (rule_filter.get('And') or {}).get('Prefix')))
        days = (rule.get('Expiration') or {}).get('Days')
        if prefix == settings.s3_moderation_prefix and days:
            return days
    return default


# ---------------------------------------------------------------- incoming mail

def incoming_message(message_id):
    """The incoming message's bytes.  S3 errors pass through."""
    response = aws_clients.s3().get_object(Bucket=settings.s3_bucket, Key=incoming_key(message_id))
    return response['Body'].read()


def delete_incoming_message(message_id):
    aws_clients.s3().delete_object(Bucket=settings.s3_bucket, Key=incoming_key(message_id))
