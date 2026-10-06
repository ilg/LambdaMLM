class UnknownList(Exception):
    pass

class ListNotFound(UnknownList):
    """The list's config isn't in S3 (as opposed to, say, being unreadable)."""
    pass

class ListChanged(Exception):
    """Something else saved the list after it was loaded, so it wasn't saved."""
    pass

class InsufficientPermissions(Exception):
    pass

class AlreadySubscribed(Exception):
    pass

class NotSubscribed(Exception):
    pass

class ClosedSubscription(Exception):
    pass

class ClosedUnsubscription(Exception):
    pass

class UnknownFlag(Exception):
    pass

class UnknownOption(Exception):
    pass

class ModeratedMessageNotFound(Exception):
    pass
