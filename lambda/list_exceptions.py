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
