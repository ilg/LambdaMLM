# -*- coding: utf-8 -*-

# The actual config file should be named "config.py"

# The user part of the email address at which commands are to be received.
command_user = 'lambda'

# The region to deploy to.  SES must receive email in this region.
lambda_region = 'us-west-2'

# The S3 bucket to use for configuration, incoming SES emails, and moderated emails.
# Bucket names are global, so this must be a name no one else has taken.
s3_bucket = 'lambdamlm'

# The prefix used for incoming SES emails.
s3_incoming_email_prefix = 'incoming/'

# The prefix used for configuration files.
s3_configuration_prefix = 'config/'

# The prefix used for moderated emails.
s3_moderation_prefix = 'moderation/'

# The key to use when generating a HMAC-SHA1 signature of a command.  Changing
# it invalidates any signed commands and invitations that are outstanding.
# (Use a raw string, r'...', if it contains backslashes.)
signing_key = u'Put some unique text here.  It’ll get used as the secret key for generating the command-validation signatures (HMAC-SHA1).'

# The interval of time for which a signed command is valid.
from datetime import timedelta
signed_validity_interval = timedelta(hours=1)


# ---------------------------------------------------------------------------
# Deployment settings, used by scripts/deploy (see docs/setup.md).

# The CloudFormation stack name.
stack_name = 'LambdaMLM'

# The SES receipt rule set to add this deployment's receipt rule to, or None to
# set up SES receipt rules yourself.  If the rule set doesn't exist, it's
# created, and if no rule set is active, it's made active.
receipt_rule_set = 'default-rule-set'

# Whether the receipt rule is enabled.  When moving an existing deployment to
# the SAM stack, deploy with this False first; see docs/setup.md.
receipt_rule_enabled = True

# The domains (or addresses) the receipt rule applies to.  Empty for all of
# the account's verified domains.
receipt_rule_recipients = []

# An email address to notify when the function reports errors, or None.
alarm_email = None

# How many days held (moderated) messages wait for a moderator before they
# expire.
moderation_expiration_days = 3
