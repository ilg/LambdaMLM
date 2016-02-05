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
- [ ] Subscribe to list
- [ ] Unsubscribe from list
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

## License

[MIT License](LICENSE)

## Author

[Isaac Greenspan](https://github.com/ilg), with some time contributed by [Vokal](http://vokal.io) Hack Days (February, 2016).
