# -*- coding: utf-8 -*-
"""Bounce classification.

The golden results were recorded from Lamson's analyzer on Python 2; the
vendored copy (lamson_bounce) reproduces them.
"""

import glob
import os

import pytest

import email_utils
import golden
from helpers import FIXTURES, parse_message, read_bytes

SAMPLES = sorted(
        glob.glob(os.path.join(FIXTURES, 'bounces', 'flufl', '*.txt'))
        + glob.glob(os.path.join(FIXTURES, 'bounces', 'synthetic', '*.eml')))


def sample_id(path):
    return '{}/{}'.format(os.path.basename(os.path.dirname(path)), os.path.basename(path))


def analyze(msg):
    """The fields of the bounce analysis that LambdaMLM's behavior depends on."""
    import lamson_bounce
    try:
        analysis = lamson_bounce.detect(msg)
    except Exception as e:
        return {'error': type(e).__name__}
    return {
        'score': analysis.score,
        'is_hard': analysis.is_hard(),
        'is_soft': analysis.is_soft(),
        'primary_status': list(analysis.primary_status),
        'secondary_status': list(analysis.secondary_status),
        'combined_status': list(analysis.combined_status),
        'action': analysis.action,
    }


def classify(msg):
    try:
        return email_utils.detect_bounce(msg).name
    except Exception as e:
        return type(e).__name__


def test_sample_count():
    assert len(SAMPLES) == 121


def test_analysis_matches_golden():
    results = {}
    for path in SAMPLES:
        msg = parse_message(read_bytes(path))
        results[sample_id(path)] = {
            'analysis': analyze(msg),
            'response_type': classify(msg),
        }
    golden.check_json('bounces.json', results)


@pytest.mark.parametrize('name, expected', [
    ('ses-permanent.eml', 'hard'),
    ('ses-transient.eml', 'soft'),
    ('arf-complaint.eml', 'unknown'),
    ('microsoft-5-1-10.eml', 'KeyError'),
    ])
def test_synthetic_samples(name, expected):
    msg = parse_message(read_bytes(FIXTURES, 'bounces', 'synthetic', name))
    assert classify(msg) == expected


def test_complaints_are_not_detected():
    # email_utils.detect_bounce has "# TODO: detect complaints" (issue #22).
    msg = parse_message(read_bytes(FIXTURES, 'bounces', 'synthetic', 'arf-complaint.eml'))
    assert email_utils.detect_bounce(msg) == email_utils.ResponseType.unknown


@pytest.mark.xfail(strict=True, raises=KeyError,
                   reason='Lamson has no entry for status codes such as 5.1.10.')
def test_unlisted_status_code_is_classified():
    msg = parse_message(read_bytes(FIXTURES, 'bounces', 'synthetic', 'microsoft-5-1-10.eml'))
    assert email_utils.detect_bounce(msg) == email_utils.ResponseType.hard
