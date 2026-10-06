import shlex
from traceback import format_exception
from types import SimpleNamespace

import click
from click.testing import CliRunner

from list_exceptions import ListChanged

runner = CliRunner()

@click.group(name='')
@click.argument('user', required=True)
@click.pass_context
def command(ctx, user, **kwargs):
    ctx.obj = SimpleNamespace(user=user)

@command.command(name='about')
@click.pass_context
def about(ctx, **kwargs):
    click.echo('This is the about command.')

@command.command(name='echo')
@click.argument('stuff', nargs=-1, required=False)
@click.pass_context
def echo(ctx, stuff, **kwargs):
    click.echo('This is the echo command.  You are {}.'.format(ctx.obj.user))
    if stuff:
        click.echo(' '.join(stuff))
    else:
        click.echo('[no parameters]')

def is_help_for_missing_arguments(exception):
    # A group invoked with no arguments replies with its help.  Click 7 exited
    # with status 0 for that; Click 8.2+ exits with status 2, from inside its
    # handler for NoArgsIsHelpError.
    return (isinstance(exception, SystemExit)
            and isinstance(exception.__context__, click.exceptions.NoArgsIsHelpError))

def run(user, cmd):
    # prog_name keeps the help text's usage line as it was under Click 7.
    result = runner.invoke(command, [user,] + shlex.split(cmd), prog_name='command')
    print('run result: {}'.format(result))
    if isinstance(result.exception, ListChanged):
        # Commands aren't retried: replaying one against a list that changed
        # underneath it isn't obviously right.
        return 'The list changed while your command was running.  Please try again.'
    if result.exception and not is_help_for_missing_arguments(result.exception):
        print('Exception: {}\nTraceback:\n {}'.format(result.exception, ''.join(format_exception(*result.exc_info))))
        return 'Internal error.'
    return result.output

# Import files with subcommands here--we don't use them directly, but we need
# to make sure they're loaded, since that's when they add their commands to
# our command object.
from . import list_commands
