from __future__ import print_function
from enum import IntEnum

import yaml

MemberFlag = IntEnum('MemberFlag', [
    'digest',
    'digest2',
    'modPost',
    'preapprove',
    'noPost',
    'diagnostic',
    'moderator',
    'myopic',
    'superadmin',
    'admin',
    'protected',
    'ccErrors',
    'reports',
    'vacation',
    'ackPost',
    'echoPost',
    'hidden',
    ])

def member_flag_representer(dumper, data):
    return dumper.represent_scalar(u'!flag', data.name)
yaml.add_representer(MemberFlag, member_flag_representer)
def member_flag_constructor(loader, node):
    value = loader.construct_scalar(node)
    return MemberFlag[value]
yaml.SafeLoader.add_constructor(u'!flag', member_flag_constructor)

class ListMember(yaml.YAMLObject):
    yaml_tag = u'!Member'
    yaml_loader = yaml.SafeLoader
    def __init__(self, address, *args, **kwargs):
        self.address = address
        self.flags = set(a for a in args if isinstance(a, MemberFlag))
    def __repr__(self):
        return u'{}({}, flags: {})'.format(
                self.__class__.__name__,
                self.address,
                ', '.join(
                    map(lambda f: f.name,
                        self.flags)
                    ),
                )
