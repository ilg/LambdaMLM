from __future__ import print_function

import lamson.encoding
import lamson.bounce
from obj import Obj

from yaml_enum import YAMLEnum

ResponseType = YAMLEnum('ResponseType', u'!bouncekind', [
    'hard',
    'soft',
    'complaint',
    'unknown',
    ])

bounce_defaults = Obj(
        bounce_score_threshold=2.0,
        bounce_weights={
                ResponseType.hard: 1.0,
                ResponseType.soft: 0.5,
                ResponseType.complaint: 3.0,
                ResponseType.unknown: 0.0,
                },
        bounce_decay_factor=0.8,
        )

def detect_bounce(msg):
    analysis = lamson.bounce.detect(Obj(base=lamson.encoding.from_message(msg)))
    print('Lamson bounce analysis: {}'.format(analysis.__dict__))
    if analysis.is_hard():
        print('Hard bounce.')
        return ResponseType.hard
    if analysis.is_soft():
        print('Soft bounce.')
        return ResponseType.soft
    # TODO: detect complaints
    return ResponseType.unknown

