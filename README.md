# LambdaMLM

A mailing list manager (MLM or email discussion list software) that runs on AWS Lambda (with help from SES and S3).

***LambdaMLM is not production-ready.  Use LambdaMLM at your own risk.***

Planned enhancements, bugs, and known limitations are tracked in [GitHub Issues](https://github.com/ilg/LambdaMLM/issues).

Setup requires familiarity with AWS—in particular, having credentials already set up locally and having familiarity with IAM and Lambda will help.  A rough outline of how to set up LambdaMLM is [here](#setup).

## Commands

A single command is sent as the subject of an email to `lambda@[domain]` where `domain` is a domain on which LambdaMLM receives email.  LambdaMLM will reply with a signed version of the command, in order to validate the address from which the command came.  The command is confirmed and executed by replying to that email.

- `about` returns an about message
- `echo [parameters]` echos the given parameters
- `list [list address]` indicates a list-specific command
	- _User-level commands:_
		- `subscribe` subscribes the sender to the list
		- `unsubscribe` removes the sender from the list
		- `setflag [flag name]` sets the given flag on the sender
		- `unsetflag [flag name]` unsets the given flag on the sender
	- _Admin commands:_  
	  (Note: An `admin` member cannot modify another `admin` member.  Only a `superAdmin` member can.  The `superAdmin` flag cannot be modified via email command.)
		- `members` returns a list of the members
		- `set [config option name] [value]` sets the value of a configuration option for the list
			- invoke without an option name to view list configuration
			- `value` is assumed to be a string
			- for boolean values, use `--true` or `--false`
			- for integer values, use `--int [value]`
		- `subscribe [address]` subscribes the given address to the list
		- `unsubscribe [address]` removes the given address from the list
		- `setflag [flag name] [address]` sets the given flag on the member with the given address
		- `unsetflag [flag name] [address]` unsets the given flag on the member with the given address

## List Configuration File Format

### Top-level properties

- `members` The list of members.  (Note: this property cannot be directly modified by email command.)
- `name` The descriptive human-readable name of the list.
- `subject-tag` The tag to prepend to the subject.
- `bounce-limit` The number of bounces a member is allowed before they no longer receives list emails (defaults to 5).
- `reply-to-list` Whether the `Reply-to:` header should be set to the list address (defaults to `false`).
- `open-subscription` Whether the list allows users to subscribe themselves (defaults to `false`).
- `closed-unsubscription` Whether the list prevents members from unsubscribing themselves (defaults to `false`).
- `moderated` Whether posts to the list are, by default, moderated (defaults to `false`).
- `reject-from-non-members` Whether messages from non-list-members are rejected (versus being moderated; defaults to `false`).
- `cc-lists` A list of other list addresses to which to send copies of any messages sent to this list.  (Note: for security/anti-spam reasons, this property cannot be modified by email command; it must be set manually in the configuration file.)

#### Members

- `address` The email address of the member.
- `flags` The flags set for the user.
- `bounce_count` The number of emails to the member that have bounced.

##### Member Flags

- `modPost` Posts from the member are moderated, regardless of list settings.
- `preapprove` Posts from the member are automatically approved (not moderated, regardless of list settings).
- `noPost` The member cannot post to the list.
- `moderator` The member is a list moderator.
- `admin` The member is a list administrator.
- `superAdmin` The member is a super-administrator.
- `vacation` No emails are sent to the member.
- `echoPost` The member receives their own posts.

### Example
```yaml
members:
- !Member
  address: admin@example.com
  flags: !!set
    !flag 'admin': null
- !Member
  address: user1@example.com
  flags: !!set {}
  bounce_count: 3
- !Member
  address: user2@example.com
  flags: !!set
    !flag 'vacation': null
name: Test List
subject-tag: TestList
reply-to-list: true
open-subscription: true
closed-unsubscription: false
moderated: false
reject-from-non-members: true
```

## Setup

Rough outline:

- AWS
	- S3
		- A bucket for LambdaMLM to use.  Put the bucket name in `config.py`.  In policies, etc., below, we'll use `lambdamlm` as the bucket name.
	- SES
		- Verify all domains to be used for lists.
		- Configure DKIM and SPF for domains.
		- Create an Email Receiving rule that applies to all domains to be used for lists with two actions:
			1. S3: Store to the S3 bucket (e.g., `lambdamlm`) with the incoming email prefix defined in `config.py` (example is `incoming/`).
			2. Lambda: Invoke the LambdaMLM function as an Event.
	- Lambda
		- Create a Lambda function named `LambdaMLM` using the Python 2.7 runtime.
		- Set the handler to `lambda.lambda_handler`.
		- Set the execution role to create a new Basic Execution role.
	- IAM
		- Mofidy the Basic Execution Role created for the Lambda function with policy (adjusting for your bucket name):
		```json
		{
		    "Version": "2012-10-17",
		    "Statement": [
		        {
		            "Effect": "Allow",
		            "Action": [
		                "logs:CreateLogGroup",
		                "logs:CreateLogStream",
		                "logs:PutLogEvents"
		            ],
		            "Resource": "arn:aws:logs:*:*:*"
		        },
		        {
		            "Effect": "Allow",
		            "Action": [
		                "s3:GetLifecycleConfiguration"
		            ],
		            "Resource": [
		                "arn:aws:s3:::lambdamlm"
		            ]
		        },
		        {
		            "Effect": "Allow",
		            "Action": [
		                "s3:PutObject",
		                "s3:GetObject",
		                "s3:DeleteObject"
		            ],
		            "Resource": [
		                "arn:aws:s3:::lambdamlm/*"
		            ]
		        },
		        {
		            "Effect": "Allow",
		            "Action": [
		                "SES:SendEmail",
		                "SES:SendRawEmail"
		            ],
		            "Resource": [
		                "arn:aws:ses:*:*:identity/*"
		            ]
		        }
		    ]
		}
		```
- Locally
	- Need [pip](https://pip.pypa.io/), [Virtualenv](https://virtualenv.pypa.io/), and [Fabric](http://fabfile.org/) installed.
	- Clone this repo.
	- In the directory, run `fab setup_virtualenv` to set up the virtual environment for LambdaMLM and install required dependencies.
	- Run `fab update_lambda` to update the Lambda function's code with your local code.

## License

[MIT License](LICENSE)

## Author

[Isaac Greenspan](https://github.com/ilg), with some time contributed by [Vokal](http://vokal.io) Hack Days (February, 2016).
