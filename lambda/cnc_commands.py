from __future__ import print_function

import shlex
from traceback import format_exception

from obj import Obj

import click
from click.testing import CliRunner

runner = CliRunner()

@click.group(name='')
@click.argument('user', required=True)
@click.pass_context
def command(ctx, user, **kwargs):
    ctx.obj = Obj(user=user)

@command.command()
@click.pass_context
def about(ctx, **kwargs):
    click.echo('This is the about command.')

@command.command()
@click.pass_context
def echo(ctx, **kwargs):
    click.echo('This is the echo command.  You are {}.'.format(ctx.obj.user))

@command.group(name='list')
@click.argument('list_address')
@click.pass_context
def list_command(ctx, list_address):
    ctx.obj.list_address = list_address

@list_command.command()
@click.argument('address', required=False)
@click.pass_context
def subscribe(ctx, address=None):
    if address is None:
        address = ctx.obj.user
    click.echo('{} wants to subscribe {} to {}.'.format(ctx.obj.user, address, ctx.obj.list_address))

def run(user, cmd):
    result = runner.invoke(command, [user,] + shlex.split(cmd))
    print('run result: {}'.format(result))
    if not result.output:
        print('Exception: {}\nTraceback:\n {}'.format(result.exception, ''.join(format_exception(*result.exc_info))))
        return 'Internal error.'
    return result.output
