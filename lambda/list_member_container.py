from __future__ import print_function

from list_member import MemberFlag
from list_exceptions import NotSubscribed, InsufficientPermissions

class ListMemberContainer (object):
    @property
    def moderator_addresses(self):
        return [
                m.address
                for m in self.members
                if MemberFlag.moderator in m.flags
                ]

    def member_passing_test(self, test):
        return next(( m for m in self.members if test(m) ), None)

    def member_with_address(self, address):
        return self.member_passing_test(lambda m: m.address == address)

    def address_will_modify_address(self, from_address, target_address):
        if from_address != target_address:
            from_member = self.member_with_address(from_address)
            # Only admin members can modify other members.
            if MemberFlag.admin not in from_member.flags:
                raise InsufficientPermissions
            target_member = self.member_with_address(target_address)
            # Only superAdmin members can modify admin members.
            if target_member and MemberFlag.admin in target_member.flags and MemberFlag.superAdmin not in from_member.flags:
                raise InsufficientPermissions

