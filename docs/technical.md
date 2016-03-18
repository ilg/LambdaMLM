# Technical Details

## Command Security/Validation

Email is very easy to forge.  To ensure that a command came from the email address we think it came from, LambdaMLM "signs" the command and sends the signed version to that address for the owner of that address to send back (via reply).  The signature is appended to the end of the command string.

Let the command string be `[command string]`, coming from `[from address]`, and expiring at `[expiration YYYYMMDDHHMMSS]`.

- The signature itself is the SHA1-HMAC, with a secret from [`config.py`](../lambda/config.example.py), of the string formed by joining the from-address, the expiration date-time string, and the command string:  
`[signature] = SHA1-HMAC("[from address] [expiration YYYYMMDDHHMMSS] [command string]")`
- A signed command is the command followed by a space, the Base64 encoding of the signature, and the expiration date-time string.

Since the SHA1-HMAC is 160 bits = 20 bytes and Base64 encoding uses trios of bytes, the signature will always have one trailing padding byte and the Base64 encoding of it will always be 27 Base64 characters followed by a `=`, so a signed command will end in something matching the regular expression `[\da-zA-Z+/]{27}=\d{14}`, where the first 28 characters (through the `=`) are the Base64-encoded signature and the remaining 14 decimal digits are the expiration date-time string (`YYYYMMDDHHMMSS`).

## Bounce Handling

Bounce handling is loosely based on [`mailman`'s bounce processing](http://www.gnu.org/software/mailman/mailman-admin/node25.html) and uses [lamson](https://github.com/ilg/lamson-bsd) to help determine what kind of bounce a given email represents.

A list member's bounce score is determined by taking the highest-scoring event for each calendar day, decaying events in the past by a factor for each day past, and totalling the day scores.  For example:

- Let hard and soft bounces have weights 1.0 and 0.5, respectively.
- Let the decay factor be 0.8.
- Suppose a user had:
	- a hard bounce and a soft bounce today
	- a hard bounce yesterday
	- a soft bounce two days ago
- The day scores are:
	- Today: max of 1.0 for the hard bounce and 0.5 for the soft bounce = 1.0
	- Yesterday: 1.0 for the hard bounce, multiplied by the decay factor = 0.8.
	- Two days ago: 0.5 for the soft bounce, multiplied by the decay factor twice = 0.32
- Total score: 1.0 + 0.8 + 0.32 = 2.12.
