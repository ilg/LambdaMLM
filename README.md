# LambdaMLM

A mailing list manager (MLM or email discussion list software) that runs on AWS Lambda (with help from SES and S3).

***This is nowhere near usable software yet.***

## Goals

### Setup/Development/Deployment via Fabric

- [ ] Command to perform initial AWS setup.
- [x] Command to re-deploy Lambda code.
- [x] Command to set up virtualenv (in .env) based on requirements.txt.

### Command and Control

- [x] Receive commands via a command user at any domain.
- [x] Reply to unsigned commands with signed version to avoid running commands from spoofed emails.
- [x] Process commands like *nix CLI commands.
- [x] Accept single command in subject.
- [ ] Accept multiple commands in body.
- [x] Maintain list configurations in S3 in YAML format

#### Commands

- [ ] Create list
- [ ] Configure list
- [x] Subscribe to list
- [x] Unsubscribe from list
- [ ] Toggle modes: vacation, echo-post, etc.
- [ ] Moderation

### Sending/Receiving Email

- [x] Validate incoming email against posting permissions
- [ ] Adjust subject, reply-to, footer, etc. per list configuration
- [x] Send email to list members
- [ ] Handle bounces
- [ ] Handle moderating messages
- [ ] Handle MIME/attachments

## Notes

- 2016-02-04: Sending via Amazon SES is likely not possible, as SES appears to require that the `From:` address be verified, which isn't plausible for discussion lists.  The best option thus far is to use an external SMTP server.  It appears to be possible to configure a given host to receive email through SES and send via an external SMTP server with both SPF and DKIM passing.

## List Configuration File Format

### Top-level properties

- `members` The list of members.
- `name` The descriptive human-readable name of the list.
- `subject-tag` The tag to prepend to the subject.
- `bounce-limit` The number of bounces a member is allowed before they no longer receives list emails (defaults to 5).
- `reply-to-list` Whether the `Reply-to:` header should be set to the list address (defaults to `false`).
- `open-subscription` Whether the list allows users to subscribe themselves (defaults to `false`).
- `closed-unsubscription` Whether the list prevents members from unsubscribing themselves (defaults to `false`).

#### Members

- `address` The email address of the member.
- `flags` The flags set for the user.
- `bounce_count` The number of emails to the member that have bounced.

##### Member Flags

- `modPost` Posts from the member are moderated, regardless of list settings.
- `preapprove` Posts from the member are automatically approved (not moderated, regardless of list settings).
- `noPost` The member cannot post to the list.
- `moderator` The member is a list moderator.  **Not yet implemented.**
- `admin` The member is a list administrator.
- `vacation` No emails are sent to the member.
- `echoPost` The member receives their own posts.

###### Potential Future Flags

Based on [ecartis](https://www.ecartis.net), descriptions from [here](https://wiki.utdallas.edu/wiki/display/FAQ/Ecartis+Account+Flags).

- `digest` User wants to receive digested version of list.
- `digest2` User wants to receive digested version of list _and_ normal posts. This flag should be set _instead_ of `digest`, not in addition to.
- `diagnostic` User is for diagnostics only, don't receive list traffic.
- `myopic` Administrative user does not receive admin postings.
- `superadmin` User is a super-administrator.
- `protected` User will never be unsubscribed by bouncer.
- `ccErrors` User wishes to have bounces cc'd to them.
- `reports` User wishes to have reports sent to them.
- `ackPost` User receives small note when a message is posted, or approved by a moderator.
- `hidden` User won't show up in membership listing of list unless viewed by an admin.

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
```

## License

[MIT License](LICENSE)

## Author

[Isaac Greenspan](https://github.com/ilg), with some time contributed by [Vokal](http://vokal.io) Hack Days (February, 2016).
