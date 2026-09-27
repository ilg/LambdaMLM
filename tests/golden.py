# -*- coding: utf-8 -*-
"""Golden files: exact outputs the tests compare against.

They were recorded from the Python 2.7 code (starting at commit 587db49), so
the Python 3 port could be checked against exactly what Python 2 produced.
Every difference the port introduced was reviewed and recorded in the port's
commit.

To re-record them:

    LAMBDAMLM_WRITE_GOLDEN=1 scripts/test

Only re-record them in a commit that deliberately changes behavior, and say
in that commit what changed and why.  Re-recording to make a failing test pass
defeats their purpose.
"""

import io
import json
import os

GOLDEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'golden')
WRITE = os.environ.get('LAMBDAMLM_WRITE_GOLDEN') == '1'


def _path(name):
    return os.path.join(GOLDEN_DIR, name)


def check_bytes(name, data):
    """Assert `data` (bytes) equals the golden file `name`."""
    assert isinstance(data, bytes)
    path = _path(name)
    if WRITE:
        if not os.path.isdir(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path))
        with open(path, 'wb') as f:
            f.write(data)
        return
    with open(path, 'rb') as f:
        expected = f.read()
    assert data == expected, 'Output differs from golden file {}'.format(name)


def check_json(name, value):
    """Assert `value` (JSON-serializable) equals the golden JSON file `name`."""
    text = json.dumps(value, indent=2, sort_keys=True, separators=(',', ': ')) + '\n'
    check_bytes(name, text.encode('utf-8'))


def load_json(name):
    with io.open(_path(name), encoding='utf-8') as f:
        return json.load(f)
