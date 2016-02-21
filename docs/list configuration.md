# List Configuration File Format

List configuration is stored in a [YAML](http://yaml.org/) file on S3.  The configruation for `some_list@host.example.com` will be in `host.example.com/some_list.yaml` prefixed by the value of `s3_configuration_prefix` in [`config.py`](../lambda/config.example.py).

## Top-level properties

- `members` The list of members.  (Note: this property cannot be directly modified by email command.)
- `name` The descriptive human-readable name of the list.
- `subject-tag` The tag to prepend to the subject.
- `bounce-score-threshold` The bounce score above which to flag a user as `bouncing` and stop sending them email (can be set system-wide in [`config.py`](../lambda/config.example.py); default is in [`email_utils.py`](../lambda/email_utils.py)).
- `bounce-weights` A dictionary of weights for each bouncing `ResponseType` (can be set system-wide in [`config.py`](../lambda/config.example.py); default is in [`email_utils.py`](../lambda/email_utils.py)).
- `bounce-decay-factor` The per-day multiplier by which bounce information decays (can be set system-wide in [`config.py`](../lambda/config.example.py); default is in [`email_utils.py`](../lambda/email_utils.py)).
- `reply-to-list` Whether the `Reply-to:` header should be set to the list address (defaults to `false`).
- `open-subscription` Whether the list allows users to subscribe themselves (defaults to `false`).
- `closed-unsubscription` Whether the list prevents members from unsubscribing themselves (defaults to `false`).
- `moderated` Whether posts to the list are, by default, moderated (defaults to `false`).
- `reject-from-non-members` Whether messages from non-list-members are rejected (versus being moderated; defaults to `false`).
- `cc-lists` A list of other list addresses to which to send copies of any messages sent to this list.  (Note: for security/anti-spam reasons, this property cannot be modified by email command; it must be set manually in the configuration file.)

### Members

- `address` The email address of the member.
- `flags` The flags set for the user.
- `bounces` A dictionary mapping when bounces were received for the member to the response type of each bounce.  Used to compute a user's bounce score.

#### Member Flags

- `modPost` Posts from the member are moderated, regardless of list settings.
- `preapprove` Posts from the member are automatically approved (not moderated, regardless of list settings).
- `noPost` The member cannot post to the list.
- `moderator` The member is a list moderator.
- `admin` The member is a list administrator.
- `superAdmin` The member is a super-administrator.
- `vacation` No emails are sent to the member.
- `echoPost` The member receives their own posts.
- `bouncing` No emails are sent to the member (set automatically by the system when a user exceeds the bounce threshold)

## Example
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
- !Member
  address: bounce@simulator.amazonses.com
  bounces:
    2016-02-19 21:08:36.249129: !bouncekind 'hard'
    2016-02-20 17:10:41.609218: !bouncekind 'hard'
    2016-02-21 19:41:01.106484: !bouncekind 'hard'
    2016-02-21 19:45:08.833041: !bouncekind 'hard'
  flags: !!set
    !flag 'bouncing': null
name: Test List
subject-tag: TestList
reply-to-list: true
open-subscription: true
closed-unsubscription: false
moderated: false
reject-from-non-members: true
```
