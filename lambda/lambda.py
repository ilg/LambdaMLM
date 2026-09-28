# The handler moved to handler.py.  This stays until a release has run with
# the new Handler setting: CloudFormation updates a function's code and its
# handler setting separately, and mail arriving in between must still find
# lambda.lambda_handler.
from handler import lambda_handler  # noqa: F401
