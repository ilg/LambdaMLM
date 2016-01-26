import shlex

import click
from click.testing import CliRunner

runner = CliRunner()

@click.group(name='')
def command(**kwargs):
    pass

@command.command()
def about(**kwargs):
    click.echo('This is the about command.')

@command.command()
def echo(**kwargs):
    click.echo('This is the echo command.')

def run(user, cmd):
    return runner.invoke(command, shlex.split(cmd)).output
