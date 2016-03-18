# -*- coding: utf-8 -*-

# The actual config file should be named "config.py"

# The user part of the email address at which commands are to be received.
command_user = 'lambda'

# The region in which to create the lambda.
lambda_region = 'us-west-2'

# The name to use for the Lambda function.
lambda_name = 'LambdaMLM'

# The name to use for the IAM role under which the Lambda function executes.
iam_role_name = 'LambdaMLM'

# The S3 bucket to use for configuration, incoming SES emails, and moderated emails.
s3_bucket = 'lambdamlm'

# The prefix used for incoming SES emails.
s3_incoming_email_prefix = 'incoming/'

# The prefix used for configuration files.
s3_configuration_prefix = 'config/'

# The prefix used for moderated emails.
s3_moderation_prefix = 'moderation/'

# The key to use when generating a HMAC-SHA1 signature of a command.
signing_key = u'Put some unique text here.  It’ll get used as the secret key for generating the command-validation signatures (HMAC-SHA1).'

# The interval of time for which a signed command is valid.
from datetime import timedelta
signed_validity_interval = timedelta(hours=1)

