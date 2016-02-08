# -*- coding: utf-8 -*-

# The actual config file should be named "config.py"

# The user part of the email address at which commands are to be received.
command_user = 'lambda'

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

# The hostname of the SMTP server to use to send email.
smtp_server = 'smtp.example.com'

# The username with which to log in to the SMTP server.
smtp_user = 'user@example.com'

# The password with which to log in to the SMTP server.
smtp_password = 'password'

