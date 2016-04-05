# API

API calls are made by invoking the lambda function manually or programmatically through the AWS Lambda API/SDK.  The API has no access control or permission management/limiting.  That is, the API has the ability to modify any and all list and member configurations.

The invocation payload should be a JSON object:

```json
{
    "Action": "APIMethodName",
    "ListAddress": "some-list@host.example.com",
    "MemberAddress": "user@example.com",
    …
}
```

The `Action` and `ListAddress` parameters are always required.  The `MemberAddress` parameter is required for actions that require a list member address.

The response will be a JSON object, containing an HTTP status code indicating if the response succeeded (e.g., 200, 201, 204 for success; 400, 404, 500 for failure).

- On success:

	```json
	{
	    "StatusCode": 200,
	    "Data": {
	        …
	    }
	}
	```

- On failure:

    ```json
	{
	    "StatusCode": 404,
	    "Message": "some-list@host.example.com not found."
	}
    ```

## Actions

### List Actions

#### `CreateList`

Create a list with the given address.

#### `UpdateList`

#### `GetList`

Return the configuration data for a list.

### Member Actions

#### `CreateMember`

Forcibly add a member to a list (that is, without confirming with the prospective list member).

#### `InviteMember`

Invite a member to a list (sends the prospective list member an email to which they must reply to be added to the list).

#### `UpdateMember`

Update the configuration data for a list member.  Takes a data structure like the one returned by `GetMember` as the parameter `Data`.

#### `GetMember`

Return the configuration data for a list member.  Example:

```json
{
  "Data": {
    "flags": [
      "moderator",
      "echoPost"
    ],
    "address": "moderator@example.com"
  },
  "StatusCode": 200
}
```

#### `UnsubscribeMember`

Invite a member to unsubscribe from a list (sends the list member an email to which they must reply to be removed from the list).

#### `DeleteMember`

Forcibly delete a member from a list (that is, without confirming with the list member).