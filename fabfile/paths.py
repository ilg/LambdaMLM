#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os

basepath = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
codedir = os.path.join(basepath, 'lambda')
libdir = os.path.join(basepath, '.env/lib/python2.7/site-packages')
zipfile = os.path.join(basepath, 'lambda.zip')
