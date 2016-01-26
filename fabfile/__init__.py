#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import pprint
pp = pprint.PrettyPrinter(indent=4)

from fabric.api import *

import boto3
client = boto3.client('lambda', region_name='us-west-2')

def update_lambda():
    basepath = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    zipfile = os.path.join(basepath, 'lambda.zip')
    codedir = os.path.join(basepath, 'lambda')
    local('zip --junk-paths "{zipfile}" "{codedir}/"*'.format(zipfile=zipfile, codedir=codedir))
    with open(zipfile) as z:
        pp.pprint(client.update_function_code(
            ZipFile=z.read(),
            FunctionName='LambdaMLM',
            ))
    local('rm "{zipfile}"'.format(zipfile=zipfile))
