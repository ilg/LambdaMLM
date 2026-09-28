"""In-memory stand-ins for the S3 and SES clients used by the Lambda code.

Only the operations the code actually calls are implemented.  Bodies are
stored as bytes and returned through a StreamingBody-like object, so the
code's stream-reading paths are exercised the way they are against real S3.
"""

import itertools

from botocore.exceptions import ClientError


def _client_error(code, message, operation):
    return ClientError(
            {'Error': {'Code': code, 'Message': message}},
            operation,
            )


def _to_bytes(data):
    # botocore encodes text blobs as UTF-8 before sending them.
    if isinstance(data, bytes):
        return data
    return data.encode('utf-8')


class FakeStreamingBody:
    """Mimics botocore's StreamingBody: read(amt=None) returning bytes."""

    def __init__(self, data):
        self._data = data
        self._position = 0

    def read(self, amt=None):
        if amt is None or amt < 0:
            chunk = self._data[self._position:]
        else:
            chunk = self._data[self._position:self._position + amt]
        self._position += len(chunk)
        return chunk

    def close(self):
        pass


class FakeS3:
    def __init__(self, log=None):
        # (bucket, key) -> bytes
        self.objects = {}
        # bucket -> lifecycle configuration dict ({'Rules': [...]})
        self.lifecycle = {}
        # Each call as (service, operation, key), shared with FakeSES so the
        # order of S3 and SES calls can be checked.
        self.log = log if log is not None else []
        # (bucket, key) pairs, or (bucket, None) for the bucket itself, that
        # fail with AccessDenied.
        self.denied = set()

    def put(self, bucket, key, data):
        """Test helper: store an object directly."""
        self.objects[(bucket, key)] = _to_bytes(data)

    def body(self, bucket, key):
        """Test helper: return a stored object's bytes."""
        return self.objects[(bucket, key)]

    def keys(self, bucket):
        return sorted(k for (b, k) in self.objects if b == bucket)

    def deny(self, bucket, key=None):
        """Test helper: make calls on this key (or the bucket's own settings) fail."""
        self.denied.add((bucket, key))

    def _call(self, operation, bucket, key=None):
        self.log.append(('s3', operation, key))
        if (bucket, key) in self.denied:
            raise _client_error('AccessDenied', 'Access Denied', operation)

    def get_object(self, Bucket, Key):
        self._call('get_object', Bucket, Key)
        try:
            data = self.objects[(Bucket, Key)]
        except KeyError:
            raise _client_error('NoSuchKey', 'The specified key does not exist.', 'GetObject')
        return {'Body': FakeStreamingBody(data), 'ContentLength': len(data)}

    def head_object(self, Bucket, Key):
        self._call('head_object', Bucket, Key)
        try:
            data = self.objects[(Bucket, Key)]
        except KeyError:
            raise _client_error('404', 'Not Found', 'HeadObject')
        return {'ContentLength': len(data)}

    def put_object(self, Bucket, Key, Body):
        self._call('put_object', Bucket, Key)
        self.objects[(Bucket, Key)] = _to_bytes(Body)
        return {}

    def delete_object(self, Bucket, Key):
        # S3 doesn't report an error when deleting a key that doesn't exist.
        self._call('delete_object', Bucket, Key)
        self.objects.pop((Bucket, Key), None)
        return {}

    def get_bucket_lifecycle_configuration(self, Bucket):
        self._call('get_bucket_lifecycle_configuration', Bucket)
        try:
            return self.lifecycle[Bucket]
        except KeyError:
            raise _client_error(
                    'NoSuchLifecycleConfiguration',
                    'The lifecycle configuration does not exist',
                    'GetBucketLifecycleConfiguration',
                    )


class FakeSES:
    def __init__(self, log=None):
        # Each call as (service, operation, destination); see FakeS3.log.
        self.log = log if log is not None else []
        # Each entry is the keyword arguments of one send call.
        self.sent_emails = []
        self.sent_raw_emails = []
        self._ids = itertools.count(1)

    def _message_id(self):
        return 'fake-message-id-{}'.format(next(self._ids))

    def send_email(self, Source, Destination, Message):
        self.log.append(('ses', 'send_email', Destination['ToAddresses'][0]))
        self.sent_emails.append(dict(
            Source=Source,
            Destination=Destination,
            Message=Message,
            ))
        return {'MessageId': self._message_id()}

    def send_raw_email(self, Source, Destinations, RawMessage):
        self.log.append(('ses', 'send_raw_email', Destinations[0]))
        self.sent_raw_emails.append(dict(
            Source=Source,
            Destinations=list(Destinations),
            Data=_to_bytes(RawMessage['Data']),
            ))
        return {'MessageId': self._message_id()}
