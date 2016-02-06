from __future__ import print_function
from enum import IntEnum

import yaml

MemberFlag = IntEnum('MemberFlag', [
    #'digest',
    #'digest2',
    'modPost',
    'preapprove',
    'noPost',
    #'diagnostic',
    'moderator',
    #'myopic',
    #'superadmin',
    'admin',
    #'protected',
    #'ccErrors',
    #'reports',
    'vacation',
    #'ackPost',
    'echoPost',
    #'hidden',
    ])

MemberFlag.userlevel_flags = classmethod(
        lambda cls: [
            cls.vacation, 
            cls.echoPost,
            ]
        )

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
        if isinstance(address, unicode):
            # Attempt to down-convert unicode-string addresses to plain strings
            try:
                address = str(address)
            except UnicodeEncodeError:
                pass
        self.address = address
        self.flags = set(a for a in args if isinstance(a, MemberFlag))
        self.bounce_count = kwargs.get('bounce_count', 0)
    def __getattr__(self, name):
        # Patch default values that might be missing in the YAML, since loading from YAML doesn't call __init__.
        if name == 'flags':
            return set()
        if name == 'bounce_count':
            return 0
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
