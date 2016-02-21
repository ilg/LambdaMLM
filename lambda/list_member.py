from __future__ import print_function
import yaml

from yaml_enum import YAMLEnum

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
