from listobj import List, UnknownList

from actions import actions
from results import InternalServerError, BadRequest

def handle_api(event):
    action = actions.get(event.get('Action'))
    if not action:
        return InternalServerError

    list_address = event.get('ListAddress')
    try:
        event['List'] = List(list_address)
    except (UnknownList, TypeError, ValueError):
        event['List'] = None

    if event['List']:
        event['Member'] = event['List'].member_with_address(event.get('MemberAddress'))
    else:
        event['Member'] = None
    try:
        return action(**event)
    except TypeError as e:
        if event.get('Debug'):
            raise
        return BadRequest(unicode(e))
