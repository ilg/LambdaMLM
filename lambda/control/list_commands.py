from functools import wraps
import click
from botocore.exceptions import ClientError

from commands import command
from listobj import List

def require_list(f):
    @wraps(f)
    def wrapper(ctx, *args, **kwargs):
        if ctx.obj.listobj is None:
            return
        return f(ctx, *args, **kwargs)
    return wrapper

@command.group(name='list')
@click.argument('list_address')
@click.pass_context
def list_command(ctx, list_address):
    ctx.obj.list_address = list_address
    try:
        ctx.obj.listobj = List(list_address)
    except ( ValueError, ClientError, ):
        click.echo('{} is not a valid list address.'.format(list_address), err=True)
        ctx.obj.listobj = None

@list_command.command()
@click.argument('address', required=False)
@click.pass_context
@require_list
def subscribe(ctx, address=None):
    if address is None:
        address = ctx.obj.user
    click.echo('{} wants to subscribe {} to {}.'.format(ctx.obj.user, address, ctx.obj.list_address))

