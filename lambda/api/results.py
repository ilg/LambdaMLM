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

