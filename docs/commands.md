# Commands

A single command is sent as the subject of an email to `lambda@[domain]` where `domain` is a domain on which LambdaMLM receives email.  LambdaMLM will reply with a signed version of the command, in order to validate the address from which the command came.  The command is confirmed and executed by replying to that email.

- `about` returns an about message
- `echo [parameters]` echos the given parameters
- `list [list address]` indicates a list-specific command
	- _User-level commands:_
		- `subscribe` subscribes the sender to the list
		- `unsubscribe` removes the sender from the list
		- `setflag [flag name]` sets the given flag on the sender
		- `unsetflag [flag name]` unsets the given flag on the sender
	- _Admin commands:_  
	  (Note: An `admin` member cannot modify another `admin` member.  Only a `superAdmin` member can.  The `superAdmin` flag cannot be modified via email command.)
		- `members` returns a list of the members
		- `set [config option name] [value]` sets the value of a configuration option for the list
			- invoke without an option name to view list configuration
			- `value` is assumed to be a string
			- for boolean values, use `--true` or `--false`
			- for integer values, use `--int [value]`
		- `subscribe [address]` subscribes the given address to the list
		- `unsubscribe [address]` removes the given address from the list
		- `setflag [flag name] [address]` sets the given flag on the member with the given address
		- `unsetflag [flag name] [address]` unsets the given flag on the member with the given address
