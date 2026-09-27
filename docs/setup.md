# Setup

LambdaMLM is deployed as an [AWS SAM](https://aws.amazon.com/serverless/sam/) stack, defined in [`template.yaml`](../template.yaml).  The stack contains:

- the Lambda function (Python 3.13),
- the S3 bucket for list configurations, incoming mail and held (moderated) messages, with lifecycle rules that expire held messages and failed incoming mail,
- the bucket policy that lets SES store incoming mail,
- the permission for SES to invoke the function,
- a queue that keeps events the function failed on for 14 days,
- an alarm on the function's errors (optionally emailed to you), and
- optionally, an SES receipt rule that stores incoming mail and invokes the function.

The command-signing key is kept in SSM Parameter Store, as the SecureString parameter `/lambdamlm/<stack name>/signing-key`.

## Where the configuration lives

**The deployed stack is the source of truth.**  Its parameters hold every setting (the function gets them as environment variables), and SSM holds the signing key, so a deployment's configuration can always be recovered from AWS:

- `scripts/find-deployments --profile PROFILE` lists the LambdaMLM stacks in an account, in every region, and any older fabfile-era deployments.
- `scripts/pull-config --env NAME --profile PROFILE --region REGION --stack STACK` writes a stack's settings into `samconfig.toml` as a named environment.

`samconfig.toml` keeps named environments (one per deployment: AWS profile, region, stack name and parameter values) so you don't have to type them.  It's specific to whoever deploys, so git ignores it; [`samconfig.example.toml`](../samconfig.example.toml) shows the format.  One file can hold environments for any number of deployments, in any number of accounts.

Local and deployed values never silently overwrite each other:

- `scripts/deploy` starts from the stack's deployed values.  If `samconfig.toml` gives a different value for any of them, it stops and lists the differences; `--apply-local-changes` deploys the local values.
- `scripts/pull-config` won't replace a local value that differs from the deployed one without `--overwrite-local`.

## Requirements

- Python 3.11 or later, for the scripts.
- The [AWS CLI](https://aws.amazon.com/cli/), with a profile for each account you deploy to.
- The [SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html).
- [Docker](https://www.docker.com/).  The function is built in SAM's Lambda build image, so its dependencies are built for Lambda whatever machine you deploy from.

## New deployment

1. In SES, in the region you'll deploy to (one where [SES receives email](https://docs.aws.amazon.com/ses/latest/dg/regions.html#region-receive-email)):
    1. Verify each domain to be used for lists, and set up DKIM and SPF for them.
    2. Point each domain's MX record at SES's inbound endpoint for the region.
    3. To send to addresses other than verified ones, request production access (move out of the SES sandbox).
2. Add an environment to `samconfig.toml` (copy `samconfig.example.toml`): the AWS profile, region and stack name, and at least `BucketName`, which must be globally unique.  The other parameters and their defaults are in `template.yaml`.
3. Create the signing key: `scripts/signing-key generate --env NAME`.
4. Deploy: `scripts/deploy --env NAME`.  It builds the function, shows the changes it's about to make, and asks before applying them.
5. Check that the deployed function validates signatures made with the stored key: `scripts/signing-key check --env NAME`.

If the environment sets `ReceiptRuleSetName`, the deployment adds a receipt rule named `<stack name>-receive` to that rule set, creating the rule set if it doesn't exist and making it active if no rule set is active yet.  Only one rule set per region can be active, so if a different one is active, the script says so and leaves it alone; name the active set in `ReceiptRuleSetName` instead.

To manage SES receipt rules yourself, leave `ReceiptRuleSetName` unset.  Your rule needs two actions, in order: store to the S3 bucket under the incoming prefix (`incoming/` by default), then invoke the function (its name is in the stack's outputs) as an Event.

## Updating

Run `scripts/deploy --env NAME` again after changing the code.  To change a setting, change it in `samconfig.toml` and run `scripts/deploy --env NAME --apply-local-changes`.  Other options are passed on to `sam deploy`; for example, `--no-confirm-changeset` applies the changes without asking.

Without a `samconfig.toml` environment, `scripts/deploy --profile PROFILE --region REGION --stack STACK` redeploys the code with the stack's current settings.

## Moving a fabfile-era deployment

A deployment made with the old fabfile has its bucket, function and IAM role outside CloudFormation, and its settings in a `config.py` packaged with the function.  To move it to a stack without losing the lists in its bucket:

1. Find it: `scripts/find-deployments --profile PROFILE` shows the function, the SES rule that invokes it, and its bucket.
2. Add an environment to `samconfig.toml` with its profile and region, a stack name (the function gets a generated name, so this can be anything, including `LambdaMLM`), and parameters matching the old `config.py`: `BucketName`, plus `CommandUser` and the prefixes if they aren't the defaults.  Set `ReceiptRuleSetName` to the active rule set that holds the existing receipt rule, and `ReceiptRuleEnabled=false`, so the new rule is created disabled and mail isn't handled by both the old and new functions.
3. Copy the old signing key into SSM, so outstanding invitations keep working: `scripts/signing-key import-from-function --env NAME --function OLD_FUNCTION_NAME`.  The key is read from the old function's `config.py` and never printed.
4. Adopt the bucket: `scripts/import-bucket --env NAME`.  It creates the stack containing only the existing bucket, without changing the bucket or its contents.
5. Deploy: `scripts/deploy --env NAME`.  It adds the rest of the stack and applies the template's bucket settings: versioning, the lifecycle rules, the bucket policy, and blocking public access.  The lifecycle rules apply to existing objects too, so held messages and failed incoming mail older than the expiry periods are deleted soon afterwards.
6. Check the key: `scripts/signing-key check --env NAME`.
7. Switch mail over from the old function to the new one; see the [modernization plan](modernization-plan.md), step 7.

## Details

The function's IAM role allows:

- `s3:GetObject`, `s3:PutObject` and `s3:DeleteObject` on objects in the bucket,
- `s3:ListBucket` and `s3:GetLifecycleConfiguration` on the bucket,
- `ses:SendEmail` and `ses:SendRawEmail`, and
- `ssm:GetParameter` on its own signing-key parameter (and `kms:Decrypt` through SSM).

The function isn't retried when it fails: a retry after a failure partway through sending a post would send it again to the members who already got it.  Failed events go to the queue named in the stack's `FailedEventsQueueUrl` output instead, and the incoming mail they refer to stays in the bucket until the incoming-mail lifecycle rule expires it.

The bucket is kept if the stack is deleted.  The signing-key parameter isn't part of the stack, so it's kept too; delete it with the AWS CLI if you're removing a deployment for good.
