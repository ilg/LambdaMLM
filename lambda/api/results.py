InternalServerError = {
        'StatusCode': 500,
        'Message': 'Internal Server Error',
        }

NotImplemented = {
        'StatusCode': 501,
        'Message': 'Not Implemented',
        }

def NotFound(obj):
    return {
            'StatusCode': 404,
            'Message': '{} not found.'.format(obj),
            }

Conflict = {
        'StatusCode': 409,
        'Message': 'The list changed while this request was running. Try again.',
        }

def BadRequest(msg):
    return {
            'StatusCode': 400,
            'Message': msg,
            }

def Success(data=None, code=200):
    return {
            'StatusCode': code,
            'Data': data,
            }

