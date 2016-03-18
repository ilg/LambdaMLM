#!/usr/bin/env python
# -*- coding: utf-8 -*-

import imp
import os

from fabric.api import task
from fabric.utils import puts, error

from .paths import codedir

@task
def check_config(use_config=None):
    if use_config:
        with lcd(codedir):
            local('cp config.{}.py config.py'.format(use_config))
    try:
        config = imp.load_source('config', os.path.join(codedir, 'config.py'))
    except IOError:
        error('config.py not found.  Did you create it by copying config.example.py?')
    try:
        config_example = imp.load_source('config_example', os.path.join(codedir, 'config.example.py'))
    except IOError:
        error('config.example.py not found.  Did you remove it?')
    if config.signing_key == config_example.signing_key:
        error('You need to change the signing key to your own unique text.')
    if config.s3_bucket == config_example.s3_bucket:
        error('You need to change the s3 bucket name to a bucket you control.')
    puts('Your config.py appears to be set up.')
    return config
