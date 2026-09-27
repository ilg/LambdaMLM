# Synthetic bounce samples

These messages were written by hand for LambdaMLM's tests. They are not copies of real messages. They imitate the formats the production deployment receives at its bounce addresses:

- `ses-permanent.eml`: an Amazon SES bounce with `Action: failed` and status 5.1.1.
- `ses-transient.eml`: the same with `Action: delayed` and status 4.4.7.
- `microsoft-5-1-10.eml`: a bounce with status 5.1.10, the "recipient not found" code Microsoft 365 uses. Lamson's bounce analyzer raises `KeyError` on status codes like this.
- `arf-complaint.eml`: an RFC 5965 feedback (complaint) report, as SES forwards complaints.

They're part of LambdaMLM and covered by its MIT license.
