from functools import wraps
import click
from botocore.exceptions import ClientError

from commands import command
import listobj

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
        ctx.obj.listobj = listobj.List(list_address)
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
    try:
        ctx.obj.listobj.user_subscribe_user(ctx.obj.user, address)
        click.echo('{} has been subscribed to {}.'.format(address, ctx.obj.list_address))
    except listobj.InsufficientPermissions:
        click.echo(
                'You do not have sufficient permissions to subscribe {} to {}.'.format(address, ctx.obj.list_address),
                err=True)
    except listobj.AlreadySubscribed:
        click.echo(
                '{} is already subscribed to {}.'.format(address, ctx.obj.list_address),
                err=True)
    except listobj.ClosedSubscription:
        click.echo('{} is not a valid list address.'.format(ctx.obj.list_address), err=True)

@list_command.command()
@click.argument('address', required=False)
@click.pass_context
@require_list
def unsubscribe(ctx, address=None):
    if address is None:
        address = ctx.obj.user
    try:
        ctx.obj.listobj.user_unsubscribe_user(ctx.obj.user, address)
        click.echo('{} has been unsubscribed from {}.'.format(address, ctx.obj.list_address))
    except listobj.InsufficientPermissions:
        click.echo(
                'You do not have sufficient permissions to unsubscribe {} to {}.'.format(address, ctx.obj.list_address),
                err=True)
    except listobj.NotSubscribed:
        click.echo(
                '{} is not subscribed to {}.'.format(address, ctx.obj.list_address),
                err=True)
    except listobj.ClosedUnsubscription:
        click.echo('{} does not allow members to unsubscribe themselves.  Please contact the list administrator to be removed from the list.'.format(ctx.obj.list_address), err=True)

