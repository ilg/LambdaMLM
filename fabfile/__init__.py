#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import pprint
pp = pprint.PrettyPrinter(indent=4)

from fabric.api import *

import boto3
client = boto3.client('lambda', region_name='us-west-2')

basepath = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

def update_lambda():
    zipfile = os.path.join(basepath, 'lambda.zip')
    codedir = os.path.join(basepath, 'lambda')
    libdir = os.path.join(basepath, '.env/lib/python2.7/site-packages')
    local('''
        cd "{codedir}"
        zip --recurse-paths "{zipfile}" * --exclude "*.pyc"
        cd "{libdir}"
        zip --recurse-paths "{zipfile}" * --exclude "*.pyc" "pip*" "docutils*" "setuptools*" "wheel*" "pkg_resources*" "*.dist-info/*"
        '''.format(
            zipfile=zipfile, 
            codedir=codedir, 
            libdir=libdir,
            ))
    with open(zipfile) as z:
        pp.pprint(client.update_function_code(
            ZipFile=z.read(),
            FunctionName='LambdaMLM',
            ))
        local('rm "{zipfile}"'.format(zipfile=zipfile))

def setup_virtualenv():
    local('''
        cd "{basepath}"
        virtualenv --no-site-packages --distribute .env \
            && source .env/bin/activate \
            && pip install -r requirements.txt
        '''.format(
            basepath=basepath,
            ))
