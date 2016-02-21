# Setup

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
	- Copy [`config.example.py`](../lambda/config.example.py) to `config.py` and edit/fill in the appropriate values.
	- Run `fab update_lambda` to update the Lambda function's code with your local code.
