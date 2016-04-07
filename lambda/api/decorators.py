from functools import wraps

from results import NotFound

def require_list(f):
    @wraps(f)
    def wrapper(**kwargs):
        if kwargs.get('List') is None:
            return NotFound('List {}'.format(kwargs.get('ListAddress')))
        return f(**kwargs)
    return wrapper

def require_member(f):
    @wraps(f)
    @require_list
    def wrapper(**kwargs):
        if kwargs.get('Member') is None:
            return NotFound('Member {}'.format(kwargs.get('MemberAddress')))
        return f(**kwargs)
    return wrapper
