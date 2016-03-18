#!/usr/bin/env python
# -*- coding: utf-8 -*-

from fabric.api import lcd, local, task

from .check_config import check_config
from .aws_lambda import create_lambda, update_lambda

from .paths import basepath

@task
def setup_virtualenv():
    with lcd(basepath):
        local('''
            virtualenv --no-site-packages --distribute .env \
                    && source .env/bin/activate \
                    && pip install -r requirements.txt
            '''.format(
                basepath=basepath,
                ))
