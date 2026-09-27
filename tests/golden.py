# -*- coding: utf-8 -*-
"""Golden files: outputs recorded from the Python 2.7 code at commit 587db49.

Characterization tests compare the code's current output against these files,
so the Python 3 port can be checked against exactly what Python 2 produced.

To (re)record them, run the suite on Python 2.7 with LAMBDAMLM_WRITE_GOLDEN=1:

    LAMBDAMLM_WRITE_GOLDEN=1 scripts/test-py2

Never re-record them from Python 3 code: that would make the tests describe
the port instead of the original behavior.  If a deliberate behavior change
alters a golden file, update it in the same commit as the change and say so.
"""

import io
import json
import os
import sys

GOLDEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'golden')
WRITE = os.environ.get('LAMBDAMLM_WRITE_GOLDEN') == '1'


def _path(name):
    return os.path.join(GOLDEN_DIR, name)


def check_bytes(name, data):
    """Assert `data` (bytes) equals the golden file `name`."""
    assert isinstance(data, bytes)
    path = _path(name)
    if WRITE:
        if sys.version_info[0] != 2:
            raise RuntimeError('Golden files must be recorded on Python 2.7.')
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
