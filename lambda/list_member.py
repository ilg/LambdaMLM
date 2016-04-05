from __future__ import print_function
import yaml
from itertools import groupby
from math import pow

from yaml_enum import YAMLEnum

from email_utils import ResponseType

MemberFlag = YAMLEnum('MemberFlag', u'!flag', [
    #'digest',
    #'digest2',
    'modPost',
    'preapprove',
    'noPost',
    #'diagnostic',
    'moderator',
    #'myopic',
    'superAdmin',
    'admin',
    #'protected',
    #'ccErrors',
    #'reports',
    'vacation',
    #'ackPost',
    'echoPost',
    #'hidden',
    'bouncing',
    ])

MemberFlag.userlevel_flags = classmethod(
        lambda cls: [
            cls.vacation, 
            cls.echoPost,
            ]
        )

class ListMember(yaml.YAMLObject):
    yaml_tag = u'!Member'
    yaml_loader = yaml.SafeLoader
    yaml_dumper = yaml.SafeDumper
    def __init__(self, address, *args, **kwargs):
        self.address = address
        self.flags = set(a for a in args if isinstance(a, MemberFlag))
    def __getattr__(self, name):
        # Patch default values that might be missing in the YAML, since loading from YAML doesn't call __init__.
        if name == 'flags':
            return set()
        raise AttributeError(name)
    def __repr__(self):
        return u'{}({}, flags: {})'.format(
                self.__class__.__name__,
                self.address,
                ', '.join(
                    map(lambda f: f.name,
                        self.flags)
                    ),
                )
    def dict(self):
        return {
                'address': self.address,
                'flags': [ f.name for f in self.flags ],
                }
    def update_from_dict(self, d):
        if 'address' in d:
            self.address = d['address']
        if 'flags' in d:
            self.flags = set(MemberFlag[f] for f in d['flags'])
    def can_receive_from(self, from_address):
        return (
                MemberFlag.vacation not in self.flags
                and MemberFlag.bouncing not in self.flags
                and (
                    MemberFlag.echoPost in self.flags
                    or from_address != self.address
                    )
                )
    def add_response(self, response_type):
        from datetime import datetime
        try:
            self.bounces[datetime.now()] = response_type
        except AttributeError:
            self.bounces = { datetime.now(): response_type, }
    def bounce_score(self, weights, decay):
        try:
            from datetime import date
            today = date.today()
            return sum(
                    (pow(decay, (today - day).days)
                        * max(weights[bounce[1]] for bounce in day_bounces))
                    for day, day_bounces
                    in groupby(
                        sorted(self.bounces.iteritems()),
                        lambda bounce: bounce[0].date()
                        )
                    )
        except AttributeError:
            return 0
