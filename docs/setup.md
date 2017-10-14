# Setup

The included `fabfile` can faciliate setting up LambdaMLM.

1. Need [pip](https://pip.pypa.io/), [Virtualenv](https://virtualenv.pypa.io/), and [Fabric](http://fabfile.org/) installed.
2. Clone this repo.
3. Copy [`config.example.py`](../lambda/config.example.py) to `config.py` and edit/fill in the appropriate values.  In particular, your S3 bucket name must be globally unique, not just unique within your account.  
  _Note:_ If you're planning to use multiple configurations, you can keep each configuration in a file named `config.somename.py` and pass `somename` as a parameter to the `fab` commands `create_lambda:somename` and `update_lambda:somename`.  The specific `somename` configuration will be copied over `config.py` before the rest of the `fab` command runs.
4. In the directory, run `fab setup_virtualenv` to set up the virtual environment for LambdaMLM and install required dependencies.
5. Run `fab create_lambda` to create the S3 bucket, an IAM role under which LambdaMLM will run (with an appropriate policy), and the lambda function itself.
6. In S3 Console, navigate to your new bucket. Click Permissions tab, then Bucket Policy button. Add in policy from [`s3policy.md`](s3policy.md), replacing `[s3_bucket]` and `[account_id]` (avaiable on the AWS My Account page).
7. In SES, in the region defined as `lambda_region` in `config.py`:
	1. Verify all domains to be used for lists.
	2. Configure DKIM and SPF for domains.
	3. Create an Email Receiving rule that applies to all domains to be used for lists with two actions:
		1. S3: Store to the S3 bucket defined in your `config.py` with the incoming email prefix defined in `config.py` (example is `incoming/`).
		2. Lambda: Invoke the lambda function as an Event.

If you make any further changes to `config.py` or to the code, run `fab update_lambda` to update the Lambda function's code with your local code.


### Technical Details

The `fab create_lambda` command:

- does a quick check of your `config.py` file
- creates the S3 bucket in the specified region.
- creates an IAM role with the name defined in `config.py` and with policy (where `[s3_bucket]` is the bucket name defined in `config.py`):
    
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
	                "arn:aws:s3:::[s3_bucket]"
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
	                "arn:aws:s3:::[s3_bucket]/*"
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
	
- creates a Lambda function with name defined in `config.py` using the Python 2.7 runtime, with the handler and role set appropriately
