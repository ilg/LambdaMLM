from __future__ import print_function

import shlex

import click
from click.testing import CliRunner

runner = CliRunner()

class Command:
    def __init__(self, user=None):
        self.user = user

    @click.group(name='')
    def command(**kwargs):
        pass

    @command.command()
    def about(**kwargs):
        click.echo('This is the about command.')

    @command.command()
    def echo(**kwargs):
        click.echo('This is the echo command.  You are {}.'.format(self.user))

def run(user, cmd):
    command = Command(user)
    result = runner.invoke(command.command, shlex.split(cmd))
    print('run result: {}'.format(result))
    return result.output
