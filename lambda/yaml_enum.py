from enum import IntEnum

import yaml

def YAMLEnum(classname, tagname, names):
    cls = IntEnum(classname, names)
    yaml.SafeDumper.add_representer(
            cls,
            lambda dumper, data: dumper.represent_scalar(tagname, data.name)
            )
    yaml.SafeLoader.add_constructor(
            tagname,
            lambda loader, node: cls[loader.construct_scalar(node)]
            )
    return cls

