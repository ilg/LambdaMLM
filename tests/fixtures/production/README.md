# Production fixtures

Sanitized data from the one live LambdaMLM deployment, taken in September 2026 by a read-only inventory of its S3 bucket. The deployment was running the code at commit 587db49, so these files are what that code actually reads and writes. Tests use them to check that the Python 3 port reads and writes existing data exactly the way the Python 2 code does.

## Contents

- `lists/example.org/*.yaml`: list config files, as stored at `config/example.org/<list>.yaml`. They were written by PyYAML 3.11's pure-Python emitter on Python 2, except `india.yaml`, which was edited by hand.
- `moderation/*.eml`: messages held for moderation, as stored under `moderation/`. They were written by Python 2's `msg.as_string()`, so their headers end in LF while their bodies keep the original CRLF line endings.
- `incoming/*.eml`: messages as SES stored them under `incoming/` (CRLF throughout).

### Oddities kept on purpose

- `juliet_test.yaml` has a name that fails `name_regex`, so `List()` can never load it. Its twin `juliet-test.yaml` loads fine.
- `india.yaml` has unsorted keys, members with no `name` key, and a trailing blank line.
- `charlie-sub-list.yaml` has a member with `address: ''` and names written as `''`, `' '`, and a quoted name with a trailing space.
- Several members' addresses contain uppercase letters, which the current code never matches (lookups lowercase the sender only).
- Members with no flags have them written in flow form, `!!set {}`; members with flags use block form, with `!flag 'name': null` entries.
- `bravo-roster.yaml` has `cc-lists` pointing at `charlie-sub-list`.

### Held messages

Each held message's S3 key is `moderation/example.org/<list>/` followed by its `Message-ID` value, with `:` replaced by `_`.

| File | List | Notes |
|---|---|---|
| `mod-01-related-utf8qp.eml` | `alpha-list` | `multipart/related` with an inline image; UTF-8 quoted-printable text |
| `mod-02-encodedwords-base64.eml` | `charlie-sub-list` | Base64 UTF-8 bodies and `utf-8?B` encoded-words. The original's `Message-ID:` header was folded, so its key starts with a space (`moderation/example.org/charlie-sub-list/ <AL1AD…>`); the stored copy no longer shows the fold |
| `mod-03-cp1252qp.eml` | `bravo-roster` | windows-1252 quoted-printable; a munged `+from` address in the body |

### Incoming messages

| File | Addressed to | Notes |
|---|---|---|
| `incoming-01-ses-setup-notification.eml` | none | The notice SES writes when an S3 action is created; never passed to the function |
| `incoming-02-list-post-pdf.eml` | `bravo-roster` | `multipart/mixed` with two quoted-printable parts and a PDF |
| `incoming-03-list-post-nested-alternative.eml` | `bravo-roster` | `multipart/alternative` containing a `multipart/mixed` |
| `incoming-04-list-post-mixedcase-sender.eml` | `delta` | `From` address has uppercase letters; `Return-Path` is lowercase |

The originals of the incoming list posts were large (0.36–3.9 MB) and made the function run out of memory. Their attachments have been cut to 20 base64 lines, so they're now small. Tests that need large messages generate them.

## How they were sanitized

Two passes, both working on raw bytes so that structure and encoding are unchanged apart from the replaced values.

**First pass** (during the inventory):

- Every email address was replaced by a consistent pseudonym of the same length under `example.com`, `example.org` or `example.net`, keeping case patterns, `+` tags, separators, and the list-address forms (`list+user=host+bounce@host`, `list+user=host+from@host`).
- Personal names were replaced word by word with same-length fake words, keeping case, punctuation, quoting and encoded-word framing.
- Message text was replaced with same-length filler words; quoted-printable was rewritten in place, and base64 was decoded, rewritten and re-encoded with the original line layout. Attachments became placeholder data of the same decoded length.
- Message-ID hosts, trace-header hostnames and IP addresses, DKIM and ARC signature values, vendor anti-spam blobs, account IDs and bucket names were replaced. MIME framing, boundaries, header order and folding, charsets and transfer encodings were kept.
- The organisation's name became `XMPL`.

**Second pass** (before adding them to this repo):

- Every list name was replaced (`alpha-list`, `bravo-roster`, …) in file names, list addresses, list-address forms, `cc-lists`, list `name:` and `subject-tag:` values, and subject tags. Names that appear in message bodies kept their original length, and the matching allowed for quoted-printable soft line breaks.
- The three largest lists were cut to a subset of their members that keeps every oddity above, the members referenced by the messages here, and every member with a moderator, admin or preapprove flag.
- Every bounce timestamp was replaced with a fake one in the same format, kept in sorted order, and members with more than 10 bounces were cut to 10 (keeping at least one of each kind).
- Large attachments were shortened as described above.

Each output was checked to parse into the same MIME tree or YAML structure as its source, and scanned for the original list names and organisation words in raw bytes, decoded headers and decoded bodies.
