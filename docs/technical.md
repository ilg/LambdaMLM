# Technical Details

## Command Security/Validation

Email is very easy to forge.  To ensure that a command came from the email address we think it came from, LambdaMLM "signs" the command and sends the signed version to that address for the owner of that address to send back (via reply).  The signature is appended to the end of the command string.

Let the command string be `[command string]`, coming from `[from address]`, and expiring at `[expiration YYYYMMDDHHMMSS]`.

- The signature itself is the SHA1-HMAC, with a secret from [`config.py`](../lambda/config.example.py), of the string formed by joining the from-address, the expiration date-time string, and the command string:  
`[signature] = SHA1-HMAC("[from address] [expiration YYYYMMDDHHMMSS] [command string]")`
- A signed command is the command followed by a space, the Base64 encoding of the signature, and the expiration date-time string.

Since the SHA1-HMAC is 160 bits = 20 bytes and Base64 encoding uses trios of bytes, the signature will always have one trailing padding byte and the Base64 encoding of it will always be 27 Base64 characters followed by a `=`, so a signed command will end in something matching the regular expression `[\da-zA-Z+/]{27}=\d{14}`, where the first 28 characters (through the `=`) are the Base64-encoded signature and the remaining 14 decimal digits are the expiration date-time string (`YYYYMMDDHHMMSS`).