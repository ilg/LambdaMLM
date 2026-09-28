# Design: Testability Refactor

The first of the step 9 redesigns in the [modernization plan](../modernization-plan.md). The plan describes it as: "create AWS clients lazily or inject them, separate persistence from list logic, use `email.policy.default`, and remove Python 2 leftovers such as `from __future__` imports and dead code." This design keeps all of that except `email.policy.default`, which it proposes moving to the sending-robustness redesign (see [Considered and not proposed](#considered-and-not-proposed)).

An independent review checked this design against the code before it was published. Its findings are incorporated below.

## Goals

- **Importing the app creates no AWS clients and freezes no settings.** The registrations that are part of the app's design stay: the YAML tags and the Click commands.
- **One place each** to swap in fake AWS services, to define the S3 key layout, and to send mail.
- **Separate functions** for the pieces the other step 9 redesigns will replace or reuse:
  - the moderation decision for a post;
  - header rewriting;
  - delivery to each recipient (queue fan-out replaces this);
  - mapping a VERP address to a list and member, and recording a bounce against a member (SES notifications reuse both);
  - handling an SES event (handler dispatch adds SNS and SQS next to this).
- **No Python 2 leftovers or dead code** in the app's own modules.

## Non-goals

- **Behavior changes of any kind.** Every commit preserves behavior:
  - the characterization tests and golden files stay as they are;
  - so does the compatibility contract in the plan;
  - and so do the S3 and SES calls: their order, their number, and which errors are caught where.
- **The other step 9 items.** This refactor makes room for them but doesn't start them: no SNS or SQS handling, no queue, no conditional writes, and no header cleanup.
- **Replacing `CliRunner` in production code, switching to `logging`, and injecting a clock.** See [Considered and not proposed](#considered-and-not-proposed).
- **The vendored `lamson_bounce.py`.** It stays as it is, so it can still be compared with upstream, `u''` literals included.

## The code today

About 1,100 statements in `lambda/`, with 98% branch coverage from 406 tests. Coverage is measured by hand, not in CI. The uncovered code:

- **A config file that sets `bounce-weights` explicitly** (`listobj.py` lines 115 and 139).
- **Dead code:** `if not l:` in `handle_bounce_to`.
- **Defensive branches in `api/actions.py`.**
- **Two lines in the vendored bounce analyzer.**
- **`obj.py`'s unused dictionary methods.**

What makes it hard to test and to extend:

- **Import-time side effects.**
  - `listobj`, `sestools` and `control` create boto3 clients when imported. So `conftest.py` has to set fake credentials, block real requests, install a fake `settings` module in `sys.modules`, and import the app in exactly that order. Its `aws` fixture then patches four module attributes (`listobj.s3`, `listobj.ses`, `sestools.s3`, `control.ses`).
  - `sestools` copies `command_user` and the bucket settings at import (`from settings import …`). A test that changes `settings.command_user` changes it for `moderate()` but not for `event_msg_is_to_command()`, which keeps the value from import time.
- **`List` does everything.** `listobj.py` (560 lines) holds all of these in one class:
  - the config model;
  - loading and saving it in S3;
  - the permission checks behind the email commands;
  - invitations;
  - the posting pipeline;
  - moderation storage and notices;
  - bounce handling.

  Its S3 key layout, a compatibility contract, is spread across `List.__init__`, `moderate()`, `sestools` and the tests' helpers.
- **Stored and effective values are tangled.** `List.__getattr__`/`__setattr__` map attribute names to hyphenated config keys. `__init__` replaces any falsy `bounce_*` value with a default by assigning to `self.bounce_score_threshold` and the like. The underscored names aren't in `list_properties`, so they become instance attributes that are never saved. This is the quirk behind `bounce-weights` being `null` in API results. It works, and the tests pin it, but only by accident of naming.
- **Circular imports.**
  - `listobj` imports `control`, for signing and for `send_response`.
  - `control`'s `commands` module imports `list_commands`, which imports `listobj`.

  Three function-level imports work around this:
  - in `moderate()`, commented "For some reason, this import doesn't work at the file level.";
  - in `list_commands.accept_invitation`;
  - in `api.actions.verify_signed_command`.
- **`List.send()` is 100 lines**, mixing four things:
  - the moderation decision;
  - `cc-lists` fan-out;
  - header rewriting;
  - a delivery loop that serializes the message again for every recipient.
- **Python 2 leftovers:**
  - `from __future__` imports in 8 files, `u''` literals and `(object)` bases;
  - `Obj`, a dictionary wrapper used in two places as a plain namespace;
  - an unused `rsplit` in `get_signed_command`, and a check there that can never be true;
  - `if not l:` in `handle_bounce_to`.

## Design

### Principle: keep the surface the tests use

The characterization tests are the safety net, so the refactor keeps every name they use working, and changes no test assertions:
- `List.send`, `List.handle_bounce_to`, `List.lists_for_addresses`, `List.moderation_expiration_days`, `List._save`, `l._s3_key` and `l._s3_moderation_prefix`;
- the `bounce_*` attributes, `bounce_defaults` and `control.sign`;
- and so on.

Where code moves, the old name becomes a thin delegator to the new function. Moving the tests to the new names, and removing the delegators, is a separate follow-up after the refactor has been deployed and compared. Every test edit the refactor itself needs is listed under [How it's verified](#how-its-verified).

### Layering

The new modules depend on each other in one direction only, from lowest to highest:

1. `aws_clients` and `settings`
2. `storage`, `mail`, `signing`, `bounces` and `sestools` (header helpers)
3. `list_member` and `listobj` (the list model)
4. `moderation`
5. `posting`
6. `control` (email commands) and `api`
7. the handler

`listobj` keeps delegators that call up the stack (`List.send` → `posting`); those import inside the function. That's the one kind of function-level import the refactor keeps, and each gets a comment saying why. The other three function-level imports go.

### Lazy AWS clients

A new module, `aws_clients.py`, is the only place clients are created:

```python
@functools.cache
def s3():
    return boto3.client('s3')
```

It has the same for `ses()` and `ssm()`, the last used by `settings.signing_key()`. Callers always write `aws_clients.s3()`, never `from aws_clients import s3`, so a test can replace the accessor. After the storage and mail changes below, only `storage.py`, `mail.py` and `settings.py` call these.

The tests' `aws` fixture:
- clears the accessors' caches before and after each test;
- monkeypatches `aws_clients.s3` and `aws_clients.ses` to return the fakes;
- makes `boto3.client` raise inside tests, so a client created any other way fails loudly.

The fake credentials and the request blocker in `conftest.py` stay as a second line of defense.

**Why lazy accessors rather than injection.** Injecting clients, or a context object holding them, would mean threading a parameter through:
- the handler;
- the API's decorators and actions;
- Click's context;
- every `List` method that reaches storage.

What injection would buy is per-test isolation, which the fixture already provides. Lazy accessors remove the import-time side effects and give the tests one place to swap services, with far less churn. If a later redesign needs a different implementation in one path (for example, an SQS worker), the storage and mail modules are the seam to replace. The clients stay out of it.

### Settings read at call time

`settings.py` keeps its module-level values, read from the environment at import, which is when Lambda has set it. Every other module reads them at call time, as `settings.command_user` and so on, never through `from settings import …`. `sestools` is the one module that needs changing.

The tests then use the real `settings.py`. Before importing the app, `conftest.py`:
1. removes any `LAMBDAMLM_*` variables already in the environment;
2. sets its own.

This replaces installing a fake module. The `aws` fixture patches `settings.signing_key`, as the fake module does today.

### Signing and mail: breaking the cycle

- **`signing.py`** takes the following from `control/__init__.py`:
  - `sign()`, `signature()`, `check_signature()` and `get_signed_command()`;
  - the three signature exceptions;
  - the token regex and timestamp format.
- **`mail.py`** takes `control.send_response` as `send_text(source, destination, subject, body)`. It also gets `send_raw(source, destination, data)`, which from then on is how every `send_raw_email` call goes out.

With both in place, `listobj` no longer imports `control`, and the cycle is gone. `control` keeps the old names as re-exports (`control.sign` and the others). Nothing changes in the token format or the signatures, which `test_signing.py` and the golden `signatures.json` pin.

### Storage: one module for the S3 layout

`storage.py` holds every S3 key and call:

| Function | Today |
|---|---|
| `list_config_key(host, username)`, `moderation_prefix(host, username)`, `incoming_key(message_id)` | the key formats, now in one place |
| `load_list_config(host, username)` → the parsed config and the object's ETag | `List.__init__` |
| `save_list_config(host, username, config)` | `List._save` |
| `hold_message(list, key, data)`, `held_message(list, key)`, `held_message_exists(list, key)`, `delete_held_message(list, key)` | `moderate()`, `user_mod_approve()`, `user_mod_reject()` |
| `moderation_expiration_days(default=3)` | `List.moderation_expiration_days` |
| `incoming_message(message_id)`, `delete_incoming_message(message_id)` | `sestools.email_message_for_event` |

**Moved as they are:**
- **YAML:** the same `safe_load` on the response stream, and the same `safe_dump` options. An empty config file still fails the way it does today.
- **Error handling:**
  - **any** `ClientError` while loading a config is `UnknownList`;
  - **any** `ClientError` on a held message is `ModeratedMessageNotFound`;
  - **any** `ClientError` reading the lifecycle configuration returns the default;
  - errors reading or deleting incoming mail pass through, as they do today.

**The ETag** isn't used yet. `List` keeps it, so that the SNS and queue redesigns can add conditional writes (`If-Match`) without changing this interface. Concurrent bounce notifications would otherwise lose updates. The conditional writes themselves change behavior, so they belong to those redesigns.

**The tests' helpers stay literal.** `config_key()` and `incoming_key()` in `tests/helpers.py` keep spelling out the key formats, because the layout is a contract. The tests should state it independently rather than reuse the code's own functions. New tests in step 1 assert the literal config, moderation and incoming keys.

### The list model: stored values and effective values

`List` keeps its public interface. Internally:

- **Stored values** are `self.config`, the dict loaded from and saved to YAML. All of these read or write it, as today:
  - `dict()`, and so the API;
  - the `set` listing;
  - `user_set_config_value`;
  - `update_from_dict`, which is the API's UpdateList.
- **Effective bounce values** become properties with the existing names: `bounce_score_threshold`, `bounce_weights` and `bounce_decay_factor`. Each returns `stored or default`: a falsy stored value, such as `0` or `{}`, is replaced by the default, exactly as today. Nothing assigns to them, so the `__setattr__` special case and the accidental instance attributes go away. The two `setattr` sites that write config keys (`update_from_dict` and `user_set_config_value`) write to `self.config` directly.

The API keeps reporting `null` for bounce settings a file doesn't set, and scoring keeps using the defaults. **Before this change**, step 1 adds tests that pin the edge cases:
- a config file with explicit `bounce-weights` (its effect in `dict()`, in the `set` listing and in scoring);
- a stored threshold of `0`.

`__getattr__` for the other properties (`self.subject_tag` and so on) stays as it is.

### Posting: decide, rewrite, deliver

`List.send()` delegates to a new `posting.py`. Each step below is a separate function, and the order is exactly today's:

1. **Parse the sender.**
   - Read `From`: the raw value, the decoded value, the name and the address.
   - This stays first. A post with no `From` header raises `TypeError` here today, before any moderation decision, and still does. Step 1 adds a test that pins it.
2. **`disposition(list, from_address)`** returns what happens to the post: rejected (not a member, or `noPost`), moderated (with the reason), or delivered.
   - This is the if-chain at the top of `send()` today, moved as it is.
   - It prints the same messages, and only when the post isn't moderator-approved.
   - A moderated post goes to `moderation.moderate`.
3. **`cc-lists` fan-out**, unchanged:
   - each list gets its own deep copy of the message;
   - `cc_chain` guards against loops;
   - `lists_for_addresses` keeps catching `TypeError`, so odd `cc-lists` values (such as a number, or a list containing `null`) still end the fan-out quietly instead of failing the post.
4. **`rewrite_headers(list, msg, sender)`** strips the DKIM signature and return path, and sets `Sender`, the munged `From`, `Reply-to`/`Cc` and the subject tag. It changes the message in place, exactly as today.
5. **Delivery.** For each recipient from `addresses_to_receive_from`, call `mail.send_raw` with the VERP address.

**Serializing once** goes in a separate commit after the move. The message is serialized the first time it's needed, then reused for the remaining recipients. That keeps "no recipients, no serialization" exactly as today. The message doesn't change inside the loop, so the bytes are identical for every recipient. A probe over all 128 fixture messages confirmed it, and the golden files fail if later recipients' bytes differ.

This saves CPU time, not memory. Measured with `tracemalloc`, a 1.5 MB post to 50 recipients peaks at the same memory either way, because each recipient's bytes are freed before the next. So the plan's claim that per-recipient serialization is "the main driver of memory use" is wrong, and the sending-robustness redesign should look for the memory elsewhere.

**Moderation** (`moderate`, `user_mod_approve`, `user_mod_reject`) moves to `moderation.py`, and uses `storage` and `mail`. `List` keeps delegators. Its notice text, template, serialization and order of calls don't change:
- to moderate: store the message, read the lifecycle, send the notices;
- to approve: get the message, send the post, delete the message;
- to reject: check the message exists, then delete it.

### Bounces: find, then record

- **`list_and_member_for_verp(address)`** returns the list and the matching member, or no member.
  - It raises `ValueError` exactly as today, for an address with no `@` or no `+`.
  - It raises `UnknownList` exactly as today, too.
  - The SES-notifications redesign reuses it.
- **`List.record_response(member, response_type)`**:
  - adds the response;
  - rescores the member;
  - flags them as bouncing past the threshold.

  It doesn't save the list. The caller saves, so that a later batch of notifications can save once.
- **`handle_bounce_to`** (kept on `List`):
  1. calls `list_and_member_for_verp`;
  2. then `detect_bounce(msg)`;
  3. then `record_response`;
  4. then saves.

  It prints the same messages as today, and saves in the same cases.

`ResponseType`, `detect_bounce` and the bounce defaults move from `email_utils.py` to `bounces.py`:
- `email_utils` stays as a re-export until the follow-up that moves the tests;
- `bounce_defaults` stays a namespace (`types.SimpleNamespace`) with the same attributes;
- the documentation's link to `email_utils.py` is updated.

### The handler

`lambda_handler` keeps its shape: an event without `Records` goes to the API. The SES branch moves into `handle_ses_event(event)`, so the handler dispatch redesign can add SNS and SQS alongside it. `handle_ses_event` still:
- iterates over the recipients in the same order;
- handles the first VERP address it finds, and stops;
- gives each list its own copy of the message.

**The module name:** move the handler into `handler.py`, change `Handler` in `template.yaml` to `handler.lambda_handler`, and keep `lambda.py` as a one-line shim (`from handler import lambda_handler`). CloudFormation updates a function's code and its handler setting in separate calls. Mail arriving between the two would otherwise find a handler that doesn't exist. It would then fail and stay in `incoming/`, and API calls from the web app would fail too. The shim goes after a release has run with the new handler.

The header helpers stay in `sestools`, and the SES event helpers move next to `handle_ses_event`. Renaming `sestools` isn't worth the churn.

### Python 2 leftovers and dead code

Removed from the app's own modules (not the vendored bounce analyzer), with no behavior change:
- `from __future__` imports;
- `# -*- coding: utf-8 -*-` lines;
- `u''` prefixes;
- `(object)` bases;
- `super(Class, self)`;
- `map` with a lambda.

Also:
- **`Obj`** is replaced by `types.SimpleNamespace`, and `obj.py` is deleted.
- **In `get_signed_command`**, the unused `rsplit` goes, and so does the `not sig or not timestamp` check, which can never be true after the regex matches.
- **In `handle_bounce_to`**, `if not l:` goes: `List` has no truth value of its own, so the check never fails.
- **The `getattr(settings, 'bounce_*', …)` fallbacks** go: `settings` never defines those names.

The tests' own leftovers go too: the `message_from_string` fallback in `helpers.parse_message`, and the `u''` literals. These edits are mechanical, and in their own commit.

## How it's verified

- **Coverage in CI first.** PR 1 adds `pytest-cov` to the test requirements, and runs `scripts/test` with `--cov-branch --cov-fail-under` set to the current total. Then "coverage doesn't drop" is checked automatically, not by hand.
- **Each commit is a pure refactor:**
  - the full suite passes;
  - golden files aren't re-recorded;
  - no test assertion changes.
- **The only test edits in the refactor:**
  - `conftest.py`: the environment variables, the `aws` fixture and making `boto3.client` raise, instead of the fake `settings` module and the four patches.
  - `test_harness.py`: its checks of the module-level clients become checks of the accessors.
  - `test_settings.py`: it patches `aws_clients.ssm` instead of `boto3.client`.
  - `test_deploy.py`: the staged files include `handler.py` as well as `lambda.py`.
  - Removing the Python 2 leftovers from the tests, in their own commit.
  - New tests.
- **New tests, added before the code they protect moves:**
  - A config file with explicit `bounce-weights`, and a stored threshold of `0`.
  - The literal S3 keys for a list config, a held message and incoming mail.
  - The order of S3 and SES calls for moderating, approving, rejecting and handling a post. `FakeS3` already records calls, but no test asserts them yet.
  - `AccessDenied` from S3 when loading a config, reading a held message and reading the lifecycle, handled as today.
  - A post with no `From` header.
  - Importing the app in a subprocess, with `boto3.client` set to raise:
    - it creates no clients;
    - every email command is registered, which `test_command_names` can't show, because it imports `list_commands` itself.
- **After each PR merges:**
  - deploy it to staging;
  - run the full end-to-end suite;
  - compare it with the step 8 baselines (the full run plus the subscription scenarios).

  No changes are expected in deliveries, headers, bodies, command output or API results. The end-to-end suite has no `cc-lists`, `reply-to-list`, moderation-reject or UpdateList scenarios, so those rely on the unit tests alone.
- **API action functions keep their names.** A `TypeError`'s text, which names the function, becomes an API `BadRequest` message.

## Order of work

Each item is one commit. They're grouped into three PRs, so each can be deployed to staging and compared on its own.

**PR 1: safety net and plumbing**

1. Coverage in CI, and the new characterization tests.
2. Remove the Python 2 leftovers and dead code from the app. The tests' leftovers go in a separate commit.
3. Read settings at call time, and make `conftest.py` use the real `settings.py`.
4. Add `aws_clients.py`, the new fixture and the subprocess import test.
5. Add `signing.py` and `mail.py`, with `control` re-exporting the old names. This breaks the import cycle.

**PR 2: persistence**

6. Add `storage.py`.
7. Separate stored and effective list values.

**PR 3: the pipeline**

8. Split out `posting.py`.
9. Serialize each post once.
10. Split out `moderation.py`.
11. Split out the bounce code (`bounces.py`, `list_and_member_for_verp`, `record_response`).
12. Add `handle_ses_event`, move the handler to `handler.py`, and keep the `lambda.py` shim.

**Follow-up, after PR 3 has run on staging:** move the tests to the new names, and remove the delegators and re-exports. That's a separate PR, with test-only changes plus the removals. Removing the `lambda.py` shim comes after a release.

## Risks

- **Anything printed while a command runs becomes part of its emailed reply.** `CliRunner` captures standard output, and `List.send` deliberately prints nothing when a moderator approves a post for this reason. Moving code into new functions must not add or move a `print` into a path a command reaches. The command tests pin the exact reply text, including `mod approve`'s.
- **Serialization.**
  - Every `as_bytes()` call keeps `policy=SEND_POLICY`.
  - Messages are still parsed with the default compat32 policy.
  - `copy.deepcopy` is kept wherever a message is shared.

  The golden `.eml` files catch any change in bytes.
- **Errors and call order.** Moving the S3 calls into `storage.py` could narrow what's caught, or reorder calls. The new `AccessDenied` and call-order tests cover both.
- **Import order.** Breaking the cycle changes which module imports which. `control/commands.py` still has to import `list_commands` for its side effect of registering the commands. The subprocess import test checks the registration.

## Considered and not proposed

- **`email.policy.default`**, which the plan's description includes.
  - Parsing relayed posts with it changes how headers are decoded and folded when written back out. That breaks the accepted contract that headers the list doesn't change are written exactly as received, and so the golden files.
  - It would also change what `msg['message-id']` returns, which the moderation keys are built from.
  - It doesn't make anything easier to test.

  It belongs in the sending-robustness redesign, which revisits header handling anyway and will change bytes deliberately.
- **Replacing `CliRunner` in production code.** It's a test utility: it replaces `sys.stdout` for the whole process, and it's the reason command output and prints are mixed. Replacing it means reimplementing how Click reports errors and help, whose Click 8 behavior step 8 has just pinned. It changes behavior at the edges, so it's a separate, deliberate change if ever.
- **Switching `print` to `logging`.** Same reason: under `CliRunner`, where output goes decides what users receive.
- **Injecting a clock.** freezegun already controls time in the tests.
- **Taking YAML registration off the global `SafeLoader`/`SafeDumper`.** It would be cleaner, but the tests `yaml.safe_load` stored configs in many places. None of the step 9 items needs it.
- **Dependency injection throughout.** See [Lazy AWS clients](#lazy-aws-clients).
- **Removing `except TypeError` from `lists_for_addresses`.** It looks like a Python 2 workaround for `cc-lists` being `None`, but it also catches other malformed `cc-lists` values that the API's UpdateList can store. Removing it would make those posts fail.

## Questions for the owner

1. **`email.policy.default`:** move it to the sending-robustness redesign, as above? *Recommended.* If so, the plan's step 9 is updated to match.
2. **Serializing each post once:** do it in this refactor (step 9 of the order of work)? It's byte-for-byte identical and needs no design. It saves CPU time, not memory, so the plan's sending-robustness item should also drop the claim about memory. *Recommended.*
3. **Moving the handler to `handler.py`** with a `lambda.py` shim for one release? *Recommended.* The alternative is to keep `lambda.py` and the tests' `importlib` workaround.
4. **The follow-up that moves the tests to the new names:** worth doing, or keep the delegators permanently? *Recommended:* do it. The delegators are noise once staging has confirmed the refactor.
