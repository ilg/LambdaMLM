from __future__ import print_function

from listobj import List, UnknownList

InternalServerError = {
        'statusCode': 500,
        'message': 'Internal Server Error',
        }

def NotFound(obj):
        return {
                'statusCode': 404,
                'message': '{} not found.'.format(obj),
                }

def handle_api(event):
    method = event.get('method')
    if not method:
        return InternalServerError

    list_address = event.get('list')
    member_address = event.get('member')

    try:
        l = List(list_address)
    except (UnknownList, TypeError, ValueError):
        if method == 'POST' and not member_address:
            # Create a list.
            return create_list(list_address)
        return NotFound('List {}'.format(list_address))

    if member_address:
        # List Member API Call
        m = l.member_with_address(member_address)
        if method == 'POST':
            if m:
                return  # TODO: conflict error?
            return create_member(l, member_address)
        if method == 'PUT':
            return update_member(l, m)
        if method == 'GET':
            return get_member(l, m)
        # Unknown method.
        return InternalServerError

    # List API Call
    if method == 'POST':
        return  # TODO: conflict error?
    if method == 'PUT':
        return update_list(l)
    if method == 'GET':
        return get_list(l)
    # Unknown method.
    return InternalServerError
    
def create_list(list_address):
    pass

def update_list(l):
    pass

def get_list(l):
    pass

def create_member(l, member_address):
    pass

def update_member(l, m):
    pass

def get_member(l, m):
    pass

