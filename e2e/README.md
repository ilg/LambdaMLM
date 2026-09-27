# End-to-end tests

These tests send real mail through a real LambdaMLM deployment and collect what arrives, so a deployment (or a change to one) can be checked against what the previous code did.  They aren't part of `scripts/test`: they need AWS credentials, a deployment and test mail accounts, and each run takes about half an hour.

Everything is run through `scripts/e2e`.  Commands that change anything only print what they would do unless given `--apply`.

## What you need

- **An environment** in `~/.config/lambdamlm-test/e2e.ini` (see [`e2e.example.ini`](e2e.example.ini)): the deployment's AWS profile, region, active SES rule set, bucket and function, and a few addresses for test inboxes on domains that deployment receives mail for.
- **Test mail accounts** in `~/.config/lambdamlm-test/mailboxes.ini`, one section per account with its address, IMAP and SMTP servers and (app) password.  Use accounts that are only for testing: the tests delete what they read.  `scripts/e2e mailboxes check` logs in to each without sending anything.
- [uv](https://docs.astral.sh/uv/), which runs the tools with boto3.

## Setting up

1. `scripts/e2e inbox setup ENV --apply` creates the test inboxes: a bucket (tagged `lambdamlm:e2e`, with a 7-day expiry), and one SES receipt rule per inbox address at the start of the active rule set, which stores that address's mail in the bucket and stops, so no later rule sees it.
2. `scripts/e2e lists setup ENV --apply` adds test lists (`e2e-test`, `e2e-moderated`, `e2e-bounces` and `e2e-subscribe`) to the deployment's bucket.  Their members are the test inboxes and mail accounts, except `e2e-subscribe`, which the subscription scenarios join and leave.  It never touches other lists and never replaces an existing one, so rerun it after new test lists are added here to create just those.

## Running

`scripts/e2e run ENV LABEL [SCENARIO ...]` runs the scenarios (all of them by default; `scripts/e2e run ENV --list` lists them).  Each sends its mail, waits for what arrives at every inbox and account (including spam folders), and saves the raw messages, a summary and the function's log lines in `~/.cache/lambdamlm-test/results/ENV/LABEL/SCENARIO/`, outside the repository because they contain the accounts' addresses.  Use a label per run, such as `py2-baseline` for the old code and `py3` for the new.

`scripts/e2e compare ENV/LABEL ENV/LABEL` compares two runs scenario by scenario: how many copies each recipient got, the differences in the delivered messages' main headers and text bodies, other recorded results, and errors in the function's logs.

`scripts/e2e inbox list ENV` lists what the test inboxes have received.

## Tearing down

`scripts/e2e lists teardown ENV --apply` removes the test lists (and any held messages for them), and `scripts/e2e inbox teardown ENV --apply` removes the receipt rules and the bucket.  Teardown only removes what setup created: rules named `lambdamlm-e2e-*`, the bucket if it has the test tag, and lists named `e2e-*`.

## Limits

- SES removes a raw 8-bit `From` display name when sending, so messages with 8-bit headers can't be sent through SES; they have to come from a server that passes them through.
- Only mail sent to the real accounts shows how those providers treat the list's mail (spam filtering, DKIM and DMARC).
