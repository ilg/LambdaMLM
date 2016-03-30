from __future__ import print_function

from listobj import List, UnknownList

InternalServerError = {
        'StatusCode': 500,
        'Message': 'Internal Server Error',
        }

def NotFound(obj):
        return {
                'StatusCode': 404,
                'Message': '{} not found.'.format(obj),
                }

def handle_api(event):
    action = actions.get(event.get('Action'))
    if not action:
        return InternalServerError

    list_address = event.get('ListAddress')
    try:
        event['List'] = List(list_address)
    except (UnknownList, TypeError, ValueError):
        event['List'] = None

    event['Member'] = l.member_with_address(event.get('MemberAddress'))
    return action(**event)
    
actions = dict(
        CreateList=create_list,
        UpdateList=update_list,
        GetList=get_list,
        CreateMember=create_member,
        InviteMember=invite_member,
        UpdateMember=update_member,
        GetMember=get_member,
        UnsubscribeMember=unsubscribe_member,
        DeleteMember=delete_member,
        )

def create_list(ListAddress, **kwargs):
    pass

def update_list(List, **kwargs):
    pass

def get_list(List, **kwargs):
    pass

def create_member(List, MemberAddress, **kwargs):
    pass

def invite_member(List, MemberAddress, **kwargs):
    pass

def update_member(List, Member, **kwargs):
    pass

def get_member(List, Member, **kwargs):
    pass

def unsubscribe_member(List, Member, **kwargs):
    pass

def delete_member(List, Member, **kwargs):
    pass

