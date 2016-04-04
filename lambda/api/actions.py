from list_member import ListMember

from decorators import require_list, require_member
from results import InternalServerError, NotImplemented, NotFound, BadRequest, Success

def create_list(ListAddress, **kwargs):
    return NotImplemented  # TODO: implement

@require_list
def update_list(List, **kwargs):
    return NotImplemented  # TODO: implement

@require_list
def get_list(List, **kwargs):
    return NotImplemented  # TODO: implement

@require_list
def create_member(List, MemberAddress, **kwargs):
    if List.member_with_address(MemberAddress):
        # Address is already subscribed.
        return BadRequest('{} is already subscribed.'.format(MemberAddress))
    List.members.append(ListMember(MemberAddress))
    List._save()
    return Success(code=201)

@require_list
def invite_member(List, MemberAddress, **kwargs):
    return NotImplemented  # TODO: implement

@require_member
def update_member(List, Member, **kwargs):
    return NotImplemented  # TODO: implement

@require_member
def get_member(List, Member, **kwargs):
    return NotImplemented  # TODO: implement

@require_member
def unsubscribe_member(List, Member, **kwargs):
    return NotImplemented  # TODO: implement

@require_member
def delete_member(List, Member, **kwargs):
    if not Member:
        # Address isn't subscribed.
        return NotFound(kwargs.get('MemberAddress', 'Member'))
    List.members.remove(Member)
    List._save()
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

