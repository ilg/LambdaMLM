from functools import wraps
import click
from botocore.exceptions import ClientError

from commands import command
import listobj

def handle_not_subscribed(user, address, list_address):
    if user == address:
        click.echo(
                'You are not subscribed to {}.'.format(list_address),
                err=True)
    else:
        click.echo(
                '{} is not subscribed to {}.'.format(address, list_address),
                err=True)

def handle_insufficient_permissions(action):
    click.echo(
            'You do not have sufficient permissions to {}.'.format(action),
            err=True)

def handle_invalid_list_address(list_address):
    click.echo('{} is not a valid list address.'.format(list_address), err=True)
    
def require_list(f):
    @wraps(f)
    @click.pass_context
    def wrapper(ctx, *args, **kwargs):
        try:
            ctx.obj.listobj = listobj.List(ctx.obj.list_address)
        except ( ValueError, ClientError, ):
            handle_invalid_list_address(ctx.obj.list_address)
            ctx.obj.listobj = None
        if ctx.obj.listobj is None:
            return
        return f(ctx, *args, **kwargs)
    return wrapper

@command.group(name='list')
@click.argument('list_address')
@click.pass_context
def list_command(ctx, list_address):
    ctx.obj.list_address = list_address

@list_command.command()
@click.argument('address', required=False)
@require_list
def subscribe(ctx, address=None):
    if address is None:
        address = ctx.obj.user
    try:
        ctx.obj.listobj.user_subscribe_user(ctx.obj.user, address)
        click.echo('{} has been subscribed to {}.'.format(address, ctx.obj.list_address))
    except listobj.InsufficientPermissions:
        handle_insufficient_permissions('subscribe {} to {}.'.format(address, ctx.obj.list_address))
    except listobj.AlreadySubscribed:
        click.echo('{} is already subscribed to {}.'.format(address, ctx.obj.list_address), err=True)
    except listobj.ClosedSubscription:
        handle_invalid_list_address(ctx.obj.list_address)

@list_command.command()
@click.argument('address', required=False)
@require_list
def unsubscribe(ctx, address=None):
    if address is None:
        address = ctx.obj.user
    try:
        ctx.obj.listobj.user_unsubscribe_user(ctx.obj.user, address)
        click.echo('{} has been unsubscribed from {}.'.format(address, ctx.obj.list_address))
    except listobj.InsufficientPermissions:
        handle_insufficient_permissions('unsubscribe {} from {}.'.format(address, ctx.obj.list_address))
    except listobj.NotSubscribed:
        handle_not_subscribed(ctx.obj.user, address, ctx.obj.list_address)
    except listobj.ClosedUnsubscription:
        click.echo('{} does not allow members to unsubscribe themselves.  Please contact the list administrator to be removed from the list.'.format(ctx.obj.list_address), err=True)

def ctx_set_member_flag_value(ctx, address, flag, value):
    if flag is None:
        try:
            click.echo('Available flags:')
            for flag, value in ctx.obj.listobj.member_own_flags(ctx.obj.user):
                click.echo('{}: {}'.format(flag.name, value))
        except listobj.NotSubscribed:
            handle_not_subscribed(ctx.obj.user, ctx.obj.user, ctx.obj.list_address)
        return
    if address is None:
        address = ctx.obj.user
    try:
        ctx.obj.listobj.user_set_member_flag_value(ctx.obj.user, address, flag, value)
        click.echo('{} flag {} on {}.'.format('Set' if value else 'Unset', flag, address))
    except listobj.NotSubscribed:
        handle_not_subscribed(ctx.obj.user, address, ctx.obj.list_address)
    except listobj.InsufficientPermissions:
        handle_insufficient_permissions('change the {} flag on {}.'.format(flag, address))
    except listobj.UnknownFlag:
        click.echo('{} is not a valid flag.'.format(flag), err=True)

@list_command.command()
@click.argument('flag', required=False)
@click.argument('address', required=False)
@require_list
def setflag(ctx, flag=None, address=None):
    ctx_set_member_flag_value(ctx, address, flag, True)

@list_command.command()
@click.argument('flag', required=False)
@click.argument('address', required=False)
@require_list
def unsetflag(ctx, flag=None, address=None):
    ctx_set_member_flag_value(ctx, address, flag, False)

@list_command.command(name='set')
@click.argument('option', required=False)
@click.argument('value', required=False)
@click.option('--true', 'boolean', flag_value=True)
@click.option('--false', 'boolean', flag_value=False)
@click.option('--int', 'integer', default=None, type=int)
@require_list
def set_config(ctx, option=None, value=None, boolean=None, integer=None):
    if option is None:
        try:
            click.echo('Configuration for {}:'.format(ctx.obj.list_address))
            for option, value in ctx.obj.listobj.user_config_values(ctx.obj.user):
                click.echo('{}: {}'.format(option, value))
        except listobj.InsufficientPermissions:
            handle_insufficient_permissions('view options on {}.'.format(ctx.obj.list_address))
        return
    if boolean is not None:
        value = boolean
    elif integer is not None:
        value = integer
    try:
        ctx.obj.listobj.user_set_config_value(ctx.obj.user, option, value)
        click.echo('Set {} to {} on {}.'.format(option, value, ctx.obj.list_address))
    except listobj.InsufficientPermissions:
        handle_insufficient_permissions('change {} on {}.'.format(option, ctx.obj.list_address))
    except listobj.UnknownOption:
        click.echo('{} is not a valid configuration option.'.format(option), err=True)

