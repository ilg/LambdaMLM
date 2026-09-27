# Modernization Plan

This plan covers adding an automated test suite to LambdaMLM, moving it from Python 2.7 to Python 3, replacing the deploy tooling, and then redesigning a few subsystems. It was drawn up in September 2026 and revised after two independent design reviews: one of the plan itself and one of the project as a whole, which compared in-place modernization against a rewrite and other options.

## Goals

- Run on a supported AWS Lambda Python runtime. The `python2.7` runtime has been blocked from function updates since May 30, 2022, so the existing deployment can't be updated at all.
- Have an automated test suite that runs in CI.
- Have deployment that works from scratch (see [#29](https://github.com/ilg/LambdaMLM/issues/29), [#31](https://github.com/ilg/LambdaMLM/issues/31), [#32](https://github.com/ilg/LambdaMLM/issues/32), [#33](https://github.com/ilg/LambdaMLM/issues/33), [#24](https://github.com/ilg/LambdaMLM/issues/24)).
- Don't break existing behavior or data without meaning to.

## Approach

Modernize in place rather than rewriting. The architecture (SES inbound → S3 → Lambda → SES outbound) is still sound, and the code's real value is a set of implicit contracts (listed below) that existing deployments and in-flight tokens depend on. Porting the existing code under characterization tests is the cheapest way to turn those contracts into an executable specification.

Principles:

- **Tests before the port.** Characterization tests are written and run against Python 2.7 first, so they describe how the code actually behaves today.
- **The port preserves behavior.** Behavior changes happen as separate, deliberate, individually tested steps, never mixed into the port.
- **Known bugs are pinned before they're fixed.** Each is first recorded as a strict `xfail` test, and the fix commit flips it.

## The production deployment

A read-only inventory of the one live deployment (September 2026) found:

- It runs exactly the code at commit 587db49, deployed in May 2016, on `python2.7` with 128 MB of memory and a 300-second timeout.
- **Moderation has never worked.** The bucket has no lifecycle configuration, so `moderate()` fails after storing the message and no moderator is ever notified. Held messages have accumulated since 2016.
- **Large posts are never delivered.** Posts of roughly 1 MB or more with attachments run out of memory at 128 MB. With two automatic retries, members at the start of the list can receive a post up to three times before the run dies.
- **Most logged errors are mail to non-list addresses** (`UnknownList` isn't caught), each followed by two retries that fail because the message was already deleted.
- **SES rejects some re-sent posts partway through the send loop:** duplicate headers such as `List-Unsubscribe`, malformed address headers, "Recipient count exceeds 50", and malformed MIME passed through unchanged.
- **Other bugs seen in the logs:**
  - A raw 8-bit `From:` header crashes the handler.
  - Lamson raises `KeyError` on status codes outside RFC 3463's base set (for example Microsoft 365's `x.1.10`), so those bounces are never recorded.
  - A `From` address with no `@` crashes `send()`.
  - `reply-to-list` adds a second `Cc` header instead of replacing the first.
- **The signing key** is a long ASCII `u"""…"""` literal. Keys longer than 64 bytes are hashed before use, which is why production avoids the #34 crash. UTF-8 encoding on Python 3 gives identical signatures. The literal contains an invalid backslash escape, which Python 3.12+ warns about.
- **A separate web app** calls the direct-invoke API. The only email commands ever run are its invitation replies (`accept_subscription_invitation` and `accept_unsubscription_invitation`).

## Compatibility contract

These must survive the port unchanged, unless a step below changes one deliberately and documents it:

- S3 key layout and prefixes (`config/<host>/<username>.yaml`, the moderation prefix, the incoming prefix).
- The list config YAML format, including the custom tags `!Member`, `!flag`, `!bouncekind`, `!!set`, and datetime keys. YAML written by Python 2 must load under Python 3 and round-trip.
- The signed-command token format and signatures (see [Technical](technical.md)). Tokens live up to 3 days (invitations, moderation) or 1 hour (commands) and will be in flight across the cutover.
- Address grammar: VERP bounce addresses (`list+user=host+bounce@host`) and munged From addresses (`list+user=host+from@host`).
- Email command syntax and reply text, including the command names embedded in invitation emails (`accept_subscription_invitation`, `accept_unsubscription_invitation`).
- Member flag names and list option names. The flags follow [Ecartis](https://www.ecartis.net)'s.
- API action names and the `{StatusCode, Data | Message}` response shape, which the web app depends on.
- Moderation keys, which are built from the raw `Message-ID` value. When the header is folded, that value starts with a space, and existing keys keep it.
- List config files whose names fail `name_regex` (for example, a name containing `_`) stay unloadable rather than being loaded under a relaxed rule.

## Decisions

- **Bounce classification during the port:** vendor `lamson/bounce.py` from the [lamson-bsd fork](https://github.com/ilg/lamson-bsd) and port it to Python 3, so classification doesn't change during the port. `flufl.bounce` was considered: it classifies DSNs differently and doesn't detect complaints either. The real bounce redesign happens in step 9.
- **BCC'd list mail:** today it's silently dropped. This is a bug and gets fixed in step 3.
- **Step 9 (redesigns)** is part of this effort, but it gets its own design and review when reached.
- **Production fixtures** go into the repo only after further sanitizing: list names are replaced, and member counts and bounce dates are faked where practical.
- **The existing backlog expires.** The lifecycle rules added in step 6 apply to existing objects too, so held moderation messages and undelivered incoming mail from the past ten years expire rather than being reviewed or re-sent. Moderators start receiving notices once moderation works; that's expected.
- **The current function's automatic retries go to 0 now**, before any of the steps below. Today no retry ever succeeds: each one either finds the message already deleted, or runs out of memory again and re-sends to the same members.
- **Escape hatch, not planned:** Lambda's block on updating Python 2.7 functions applies to zip deployments only. A container image built on AWS's still-published `public.ecr.aws/lambda/python:2.7` base image could be deployed if something goes badly wrong.

## Steps

Steps 3, 4 and 5 each depend on the one before. Step 6 can be developed in parallel with steps 1–5 but must be finished before step 7. Because the Python 2.7 function can't be updated, nothing from steps 3–6 reaches production until the step 7 cutover, which ships all of them together.

### 1. Test harness and CI

- In-memory fakes for the S3 and SES operations the code uses: `get_object`, `put_object`, `delete_object`, `head_object`, `get_bucket_lifecycle_configuration`, `send_email`, `send_raw_email`. moto isn't used: the Python 2–compatible versions conflict with the pinned runtime dependencies, need a hand-maintained constraints file to install, and reject `send_raw_email` from the per-recipient VERP sender addresses.
  - S3 bodies must be stream objects (`io.BytesIO`, or `StringIO` on Python 2), so the code's `message_from_file(Body)`, `safe_load(Body)` and `.read()` paths are actually exercised.
  - Swap the fakes in through a single fixture that monkeypatches the module-level clients (`listobj.s3`, `listobj.ses`, `sestools.s3`, `control.ses`), so the step 9 refactor only has to change one place.
- `conftest.py`, in this order:
  1. Set fake `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and `AWS_DEFAULT_REGION`, and unset `AWS_PROFILE`. The clients are created at import time and must never pick up real credentials.
  2. Install a fake `config` module in `sys.modules`.
  3. Put `lambda/` on `sys.path`.
  4. Import the app modules. The handler module is named `lambda`, a Python keyword, so it has to be loaded with `importlib.import_module('lambda')`.
- Split requirements into runtime and dev. Pin the Python 2 test dependencies in a constraints file (`pytest==4.6.11`, `more-itertools<6`, `pluggy<1`, `mock`, `freezegun==0.3.15`, `boto3==1.17.112`), because pip on Python 2 uses the legacy resolver.
- CI: GitHub Actions running in a `python:2.7` container. Don't `apt-get` in it, because the image's package repositories are archived.
- No production code changes.

### 2. Characterization tests

Unit tests for signing and verification, bounce scoring, member flags and `can_receive_from`, permission checks, list address validation and VERP addresses, header rewriting in `List.send`, API actions and decorators, and email commands via `commands.run()`. Also `lambda_handler` end to end with the fakes.

Fixtures and assertions:

- Sanitized production data: the list configs, held moderation messages and a small leftover incoming message from the inventory, with list names replaced and member counts and bounce dates faked where practical. Keep the oddities the inventory found: an empty `address`, members without a `name` key, `!!set {}` flow sets, a hand-edited file with unsorted keys, uppercase addresses, and a list name that fails `name_regex`.
- Large messages (for the memory and timeout cases) generated by the tests rather than stored in the repo.
- Bounce samples from `flufl.bounce`'s test data (Apache-2.0), in their own directory with attribution and the license text. No real bounce emails survive in production.
- Raw 8-bit mail (headers and bodies with no encoded words and no declared charset), with assertions on the exact bytes handed to `send_raw_email`.
- `json.dumps()` of every API result, to pin the JSON shape. Saved lists hold `bounce-weights` keyed by `IntEnum`, which serializes differently on Python 2 and 3.
- Signature values computed through `signature()` / `check_signature()` with fixed timestamps.
- Bounce fixtures, including SES mailbox simulator bounces and a complaint. For each, record `(ResponseType, score, primary_status)`.
- Non-ASCII generated headers ([#9](https://github.com/ilg/LambdaMLM/issues/9)) and non-ASCII command arguments. The latter crash on Python 2 (`shlex`, `hmac`) and are expected to start passing on Python 3.
- Mail with no subject, for both commands and list posts.
- Mixed-case addresses: subscribe, then unsubscribe and set flags.
- A non-member trying to act on another member's address.
- A missing lifecycle configuration, and a `Filter`-style lifecycle rule.
- `command_user` set to something other than `lambda`.
- `cc-lists` pointing at each other.
- BCC'd list mail.
- `err=True` output and the "Internal error." path through `commands.run()`.
- Don't compare exact strings for output that includes dict reprs, such as the `set` listing, because dict ordering differs between Python versions.

Known bugs are recorded as `xfail(strict=True)` tests that reference the issue or the step 3 fix.

### 3. Bug fixes on Python 2

Each fix flips a pinned test from step 2. Keep this step to fixes that have tests; step 7's smoke tests cover each one again.

- **Keep incoming mail until it's handled successfully.** Today `sestools.email_message_for_event` deletes it in a `finally` block, even when handling fails. The retry and expiry consequences are handled in step 6.
- **Give every Click command an explicit `name=`.** This must come before the Click 7 upgrade, which turns underscores in function-derived names into dashes.
- **Use `config.command_user` in `moderate()`** instead of the hardcoded `lambda@`.
- **Tolerate a missing or `Filter`-style lifecycle configuration in `moderate()`.** Use `.get()` throughout: `Filter` may hold `Prefix` directly or under `And`, and `Expiration` and `Status` may be absent. Fall back to the existing 3-day default.
- **Make member lookups ignore case.** This covers `member_with_address` and the VERP match in `handle_bounce_to`. Lowercasing new addresses in `add_member` alone wouldn't fix members already stored in mixed case.
- **Catch `UnknownList`** in `List.lists_for_addresses` (today mail to a non-list address crashes the handler) and in `require_list` in `control/list_commands.py` (today a command for an unknown list replies "Internal error.").
- **Mail with no subject:**
  - Ignore command mail with no subject. Replying with a signed empty command would be an auto-responder anyone could trigger.
  - Treat a missing subject on list posts as empty.
- **BCC'd list mail:** route on `receipt.recipients` alone instead of intersecting it with the header-derived `mail.destination`. Keep the requirement that commands be addressed in `To:`.
  - This is a behavior change: BCC'd spam to a list, which is currently dropped, will be processed under the list's own policy. With `allow-from-non-members: true`, that means relayed to every member. Document it in the commit and in [List Configuration](list%20configuration.md).
- **`reply-to-list`:** replace any existing `Cc` header rather than adding a second one.
- **A `From` address with no `@`:** handle it instead of crashing `send()`.
- **Optional:** return `InsufficientPermissions` rather than crashing when a non-member acts on another address, and add a cycle guard for `cc-lists`.

### 4. Dependencies: last Python 2–compatible versions

One commit each:

- Click 7.1.2
- Jinja2 2.11.3, with `MarkupSafe<2.1` pinned (Jinja2 2.11 doesn't import with MarkupSafe 2.1+)
- PyYAML 5.4.1

### 5. Port to Python 3

Target `python3.13` or `python3.14`. `python3.10` is deprecated on Lambda from October 31, 2026.

- Syntax and standard-library fixes: `unicode()`, `.iteritems()`, relative imports inside the `control` and `api` packages.
- `email.message_from_bytes(Body.read())` in `sestools.email_message_for_event` and `List.user_mod_approve`.
- `as_bytes()` instead of `as_string()` for SES sends and moderation storage. On Python 3, `as_string()` replaces undeclared 8-bit bytes with U+FFFD.
- `signature()`: encode both the key and the message as UTF-8, and decode the base64 result to text. This fixes [#34](https://github.com/ilg/LambdaMLM/issues/34). For ASCII keys, signatures are byte-identical to Python 2's, so in-flight tokens stay valid.
- `List.dict()`: return a list of members, not a `map`, and key `bounce-weights` by flag name. This changes the API shape; document it in [API](api.md).
- Remove `enum34` from requirements **and uninstall it from the environment**. On Python 3.6+ it shadows the standard library `enum` and breaks `re`.
- PyYAML 6.0.3. Version 5.4.1 doesn't build on Python 3.10+.
- Modern test tooling.
- Vendored `bounce.py`:
  - Replace lamson's `MailBase` with a roughly 30-line adapter over `email.message.Message` (`walk()`, `get()`, `get_payload()`). Don't vendor `lamson/encoding.py`.
  - Keep the BSD-3-Clause copyright and license text (2008 Zed A. Shaw) with the file.
  - Assert that the bounce fixtures reproduce exactly the `(ResponseType, score, primary_status)` recorded on Python 2.
  - Drop the lamson dependency.
  - Complaints will still be classified `unknown`, exactly as today. That's expected; step 9 fixes it.
- Put the vendored-bounce commit first, so the suite never fails just because lamson can't be imported.
- After the port, as a separate commit: stop the vendored bounce analyzer raising `KeyError` on status codes outside RFC 3463's base set.
- Keep moderation keys exactly as today, including a leading space from a folded `Message-ID`. Python 3's email parser must be checked for this specifically.
- The signing-key tests include a key longer than 64 bytes, matching production.
- Expect the strict xfails for Python 2 non-ASCII crashes to start passing, and flip them.

### 6. Deploy tooling: AWS SAM

AWS SAM rather than plain CloudFormation, because step 9's SNS and SQS event sources are simple to declare in SAM. The fabfile is removed.

- Lambda function on the Python 3 runtime, with a `Timeout` well above 10 seconds and at least 512 MB of memory. Production runs out of memory at 128 MB.
- IAM role, including `s3:ListBucket` (without it, S3 reports a missing key as 403 rather than 404, which makes #33-style problems hard to diagnose) and `kms:Decrypt` if the receipt rule encrypts.
- `AWS::Lambda::Permission` allowing `ses.amazonaws.com` to invoke the function, with `SourceAccount` and `SourceArn`.
- Bucket policy letting SES write, with `SourceAccount` and `SourceArn` conditions ([#29](https://github.com/ilg/LambdaMLM/issues/29)).
- Lifecycle rules:
  - For the moderation prefix, with a `Prefix` exactly equal to `config.s3_moderation_prefix`.
  - An expiry for `incoming/`, because failed messages are now kept.
  - Both apply to existing objects, so the production backlog (held messages since 2016 and undelivered large posts) expires shortly after the rules are added. That's intended.
- Bucket versioning.
- Async invoke configuration:
  - `MaximumRetryAttempts: 0`, because a retry after a partial send would deliver the post twice to some recipients.
  - A failure destination or dead-letter queue, for manual replay.
  - A CloudWatch alarm on `Errors`.
  - Step 9 reintroduces retries once sends are idempotent.
- A script step for `SetActiveReceiptRuleSet`, which CloudFormation can't express.
- **Existing bucket:** CloudFormation can't create a bucket that already exists. Decide here between these options, preferring the first or second:
  - Import it into the stack.
  - Pass it as a parameter, with the bucket policy in the stack and versioning and lifecycle set by the script.
  - Create a new bucket and copy `config/` and `moderation/` before the cutover.
- **Config delivery:** either keep bundling `config.py` in a build step, or move to environment variables or SSM. `signed_validity_interval` (a `timedelta`) and `bounce_weights` (enum-keyed) would need a small config loader. Keep an equivalent of the fabfile's `check_config` guard. The signing key must reach the new function as exactly the same bytes. The production key's literal contains an invalid backslash escape, so if it stays in a Python file, write it as a raw string or with the backslash doubled; either gives the same value without the Python 3.12+ warning.
- Don't build in the assumption that SES is the only event source. SNS and SQS events in step 9 also carry `Records`.
- Pin or bundle boto3, so the tests and production use the same version.
- Keep `*.dist-info` in the bundle (the old fabfile excluded it).
- Update [Setup](setup.md), [API](api.md) (`bounce-weights` isn't `null` after any save, and its keys change in step 5), and [Technical](technical.md). Credit Ecartis as the source of many concepts and behaviors.

### 7. Cutover

- **Staging:** a separate domain or subdomain whose receipt rule lives in the *same* active rule set as production. Only one rule set per region can be active, so activating a separate staging rule set would switch production off.
- **Smoke tests on staging, then on production:**
  - A command and its signed reply.
  - A list post.
  - A BCC'd post from a non-member.
  - Moderation approval.
  - A bounce and a complaint (via `complaint@simulator.amazonses.com`).
  - An 8-bit message.
  - A non-ASCII display name.
  - Each step 3 fix.
- **Production:**
  1. Create a new function from the stack; don't upgrade the existing function in place, because AWS doesn't allow reverting a runtime upgrade.
  2. Before switching, confirm that an invitation token signed by the old function validates on the new one, and that the web app works against the new function's API responses.
  3. Repoint the SES receipt rule's Lambda action to the new function.
  4. Keep the old Python 2.7 function untouched for at least 3 days (the invitation lifetime) and the moderation lifecycle window, as the rollback target. Then delete it.

### 8. Dependencies: current versions

- Click 8, testing `CliRunner` / `Result.output` behavior for `err=True` output and the "Internal error." path.
- Jinja2 3 with current MarkupSafe.

### 9. Redesigns

Each of these gets its own design and review before implementation.

- **Bounces and complaints via SES notifications:** SES bounce and complaint notifications (SNS or event publishing) replace email-parsed bounces, which fixes [#22](https://github.com/ilg/LambdaMLM/issues/22) and enables [#11](https://github.com/ilg/LambdaMLM/issues/11). Email feedback forwarding stays on until this lands. Decide what happens to the vendored `bounce.py` (keep it as a fallback, or remove it).
- **Sending through a queue, with fan-out** ([#30](https://github.com/ilg/LambdaMLM/issues/30)): per-recipient sends that can be retried safely, with retries reintroduced.
- **Sending robustness:**
  - Clean up the headers SES rejects on re-sent posts (duplicate headers, malformed address headers, the recipient-count limit).
  - Decide what to do with malformed MIME.
  - Serialize each post once rather than once per recipient; per-recipient serialization is the main driver of memory use.
- **Testability refactor:** create AWS clients lazily or inject them, separate persistence from list logic, use `email.policy.default`, and remove Python 2 leftovers such as `from __future__` imports and dead code (for example the unused `rsplit` in `get_signed_command` and `if not l:` in `handle_bounce_to`).
- **Handler dispatch** on the event source (SES, SNS or SQS).

## Out of scope

Feature requests stay out of this effort: [#3](https://github.com/ilg/LambdaMLM/issues/3), [#4](https://github.com/ilg/LambdaMLM/issues/4), [#6](https://github.com/ilg/LambdaMLM/issues/6), [#7](https://github.com/ilg/LambdaMLM/issues/7), [#12](https://github.com/ilg/LambdaMLM/issues/12), [#16](https://github.com/ilg/LambdaMLM/issues/16), [#17](https://github.com/ilg/LambdaMLM/issues/17), [#27](https://github.com/ilg/LambdaMLM/issues/27) and [#28](https://github.com/ilg/LambdaMLM/issues/28). The step 9 refactor shouldn't rule any of them out.
