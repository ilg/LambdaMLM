# -*- coding: utf-8 -*-

# The actual config file should be named "config.py"

# The user part of the email address at which commands are to be received.
command_user = 'lambda'

# The S3 bucket where SES will put incoming email messages.
email_bucket = 'lambdamlm'

# The key to use when generating a HMAC-SHA1 signature of a command.
signing_key = u'Put some unique text here.  It’ll get used as the secret key for generating the command-validation signatures (HMAC-SHA1).'

