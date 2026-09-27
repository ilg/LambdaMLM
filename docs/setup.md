# Setup

LambdaMLM is deployed as an [AWS SAM](https://aws.amazon.com/serverless/sam/) stack, defined in [`template.yaml`](../template.yaml), by [`scripts/deploy`](../scripts/deploy).  The stack contains:

- the Lambda function (Python 3.13),
- the S3 bucket for list configurations, incoming mail and held (moderated) messages, with lifecycle rules that expire held messages and failed incoming mail,
- the bucket policy that lets SES store incoming mail,
- the permission for SES to invoke the function,
- a queue that keeps events the function failed on for 14 days,
- an alarm on the function's errors (optionally emailed to you), and
- optionally, an SES receipt rule that stores incoming mail and invokes the function.

## Requirements

- The [AWS CLI](https://aws.amazon.com/cli/), with credentials for the account to deploy to.
- The [SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html).
- [Docker](https://www.docker.com/).  The function is built in SAM's Lambda build image, so its dependencies are built for Lambda whatever machine you deploy from.

## New deployment

1. Clone this repository.
2. Copy [`lambda/config.example.py`](../lambda/config.example.py) to `lambda/config.py` and fill in your values.  In particular:
    - `signing_key` must be your own unique text.
    - `s3_bucket` must be globally unique (not just within your account).  The stack creates the bucket.
    - `lambda_region` must be a region where [SES can receive email](https://docs.aws.amazon.com/ses/latest/dg/regions.html#region-receive-email).
    - The deployment settings at the end (`stack_name`, `receipt_rule_set` and so on) control the stack.

    `config.py` is packaged with the function and isn't committed to git.
3. In SES, in `lambda_region`:
    1. Verify each domain to be used for lists.
    2. Set up DKIM and SPF for those domains.
    3. Point each domain's MX record at SES's inbound endpoint for the region.
    4. To send to addresses other than verified ones, request production access (move out of the SES sandbox).
4. Run `scripts/deploy`.  It builds the function, shows the changes it's about to make, and asks before applying them.

If `receipt_rule_set` is set, the deployment adds a receipt rule named `<stack_name>-receive` to that rule set, creating the rule set if it doesn't exist and making it active if no rule set is active yet.  Only one rule set per region can be active, so if a different one is active, the script says so and leaves it alone; add the rule to the active set instead by naming it in `receipt_rule_set`.

To manage SES receipt rules yourself, set `receipt_rule_set = None`.  Your rule needs two actions, in order: store to the S3 bucket under the incoming prefix (`incoming/` by default), then invoke the function (its name is in the stack's outputs) as an Event.

## Updating

Run `scripts/deploy` again after changing the code or `config.py`.  Options are passed on to `sam deploy`; for example, `scripts/deploy --no-confirm-changeset` applies the changes without asking.

## Moving an existing deployment

A deployment made with the old fabfile has its bucket, function and IAM role created outside CloudFormation.  To move it to a stack without losing the lists in its bucket:

1. Update its `lambda/config.py`:
    - Add the deployment settings from the end of `config.example.py`.
    - Set `receipt_rule_set` to the name of the active rule set that holds the existing receipt rules, and set `receipt_rule_enabled = False`.  The new rule is then created disabled, so mail isn't handled by both the old and new functions.
    - If `signing_key` contains a backslash, write it as a raw string (`r'...'`) or double the backslash.  Either keeps the same value without Python 3's warning about invalid escape sequences.  Keep the value exactly the same, or outstanding invitations stop working.
2. Run `scripts/import-bucket`.  It creates the stack containing only the existing bucket, without changing the bucket or its contents.
3. Run `scripts/deploy`.  It adds the rest of the stack and applies the template's bucket settings: versioning, the lifecycle rules, the bucket policy, and blocking public access.  The lifecycle rules apply to existing objects too, so held messages and failed incoming mail older than the expiry periods are deleted soon afterwards.
4. Switch mail over from the old function to the new one; see the [modernization plan](modernization-plan.md), step 7.

## Details

The function's IAM role allows:

- `s3:GetObject`, `s3:PutObject` and `s3:DeleteObject` on objects in the bucket,
- `s3:ListBucket` and `s3:GetLifecycleConfiguration` on the bucket, and
- `ses:SendEmail` and `ses:SendRawEmail`.

The function isn't retried when it fails: a retry after a failure partway through sending a post would send it again to the members who already got it.  Failed events go to the queue named in the stack's `FailedEventsQueueUrl` output instead, and the incoming mail they refer to stays in the bucket until the incoming-mail lifecycle rule expires it.

The bucket is kept if the stack is deleted.
