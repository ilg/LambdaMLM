# -*- coding: utf-8 -*-

from os.path import dirname
from jinja2 import Environment, FileSystemLoader
jinja = Environment(loader=FileSystemLoader(dirname(__file__)))

def render(template_name, **kwargs):
    return jinja.get_template(template_name).render(**kwargs)

