from list_member import ListMember
from list_exceptions import AlreadySubscribed, NotSubscribed

from decorators import require_list, require_member
from results import InternalServerError, NotImplemented, NotFound, BadRequest, Success

def create_list(ListAddress, **kwargs):
    if kwargs.get('List'):
        return BadRequest('{} already exists.'.format(ListAddress))
    return NotImplemented  # TODO: implement

@require_list
def update_list(List, Data, **kwargs):
    try:
        List.update_from_dict(Data)
    except KeyError:
        return BadRequest('Invalid data.')
    return Success(List.dict())

@require_list
def get_list(List, **kwargs):
    return Success(List.dict())

@require_list
def create_member(List, MemberAddress, **kwargs):
    try:
        List.add_member(MemberAddress)
    except AlreadySubscribed:
        return BadRequest('{} is already subscribed.'.format(MemberAddress))
    return Success(code=201)

@require_list
def invite_member(List, MemberAddress, **kwargs):
    try:
        List.invite_subscribe_member(MemberAddress)
    except AlreadySubscribed:
        return BadRequest('{} is already subscribed.'.format(MemberAddress))
    return Success(code=204)

@require_member
def update_member(List, Member, Data, **kwargs):
    try:
        List.update_member_from_dict(Member, Data)
    except KeyError:
        return BadRequest('Invalid data.')
    return Success(Member.dict())

@require_member
def get_member(List, Member, **kwargs):
    return Success(Member.dict())

@require_member
def unsubscribe_member(List, Member, **kwargs):
    try:
        List.invite_unsubscribe_member(Member)
    except NotSubscribed:
        # The require_member decorator already checked that the member was
        # subscribed, so if we got here, something's very broken.
        return InternalServerError
    return Success(code=204)

@require_member
def delete_member(List, Member, **kwargs):
    try:
        List.remove_member(Member)
    except NotSubscribed:
        # The require_member decorator already checked that the member was
        # subscribed, so if we got here, something's very broken.
        return InternalServerError
    return Success(code=204)

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

