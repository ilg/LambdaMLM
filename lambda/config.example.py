# -*- coding: utf-8 -*-

# The actual config file should be named "config.py"

# The user part of the email address at which commands are to be received.
command_user = 'lambda'

# The S3 bucket where SES will put incoming email messages.
email_bucket = 'lambdamlm'

# The S3 bucket where runtime-writable configurations, including list configurations, are kept.
config_bucket = 'lambdamlm-config'

# The key to use when generating a HMAC-SHA1 signature of a command.
signing_key = u'Put some unique text here.  It’ll get used as the secret key for generating the command-validation signatures (HMAC-SHA1).'

# The hostname of the SMTP server to use to send email.
smtp_server = 'smtp.example.com'

# The username with which to log in to the SMTP server.
smtp_user = 'user@example.com'

# The password with which to log in to the SMTP server.
smtp_password = 'password'

