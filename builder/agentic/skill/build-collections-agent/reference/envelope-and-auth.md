# Request envelopes, authentication and response envelopes of the tool API

Read this when `openapi_summary` prints `ENVELOPE:` or `AUTH scheme`, or when a document (service contract, integration doc) says that requests are wrapped,
carry a token or required headers, or that answers have a fixed outer shape. Everything here is generic: names come from the API and the documents.

## 1. Request envelope (`ENVELOPE: ... inside the object '<wrap>'`)
The model-facing fields of the tool are the INNER fields (the summary already lists them flat). Declare them as leaves under `body.properties` as always
(lint checks these names). The wrapped body is built in the tool's `pre_process_code` hook, which rewrites the whole request:

```python
b = config.get('body') or {}
if isinstance(b, str):
    import json; b = json.loads(b)
config['body'] = {'<wrap>': b, '<other key>': {<metadata fields the documents say to send, from call variables when they exist>}}
config.setdefault('headers', {})['Content-Type'] = 'application/json'
```
- Use the wrapper name and the other keys exactly as `ENVELOPE:` prints them. Other keys that are metadata (caller number, language) are filled from call
  variables if the documents define such variables, else sent with the values the documents show, else left out when the schema marks them optional.
- A value the documents say must be sent exactly as another service returned it (an identifier) is carried in a variable and never rebuilt from what the caller says.
- Wrap every tool the same way, including lifecycle and `pre_actions` calls. No `{{` / `}}` inside the code.

## 2. Authentication (`AUTH scheme ...`, or a token section in the documents)
- Bearer / API-key scheme: every call sends the header the scheme names (`Authorization: Bearer {{access_token}}`). Put it in the same `pre_process_code`
  (`config['headers']['Authorization'] = 'Bearer ' + vars.get('access_token', '')`), with `Accept: application/json` when the documents ask for it.
- If the summary prints `TOKEN FLOW:` (an OAuth2 clientCredentials tokenUrl) there is a tool `oauth_token`: copy `templates/token_step_node.json` as an `api_request` node right after the setup node (replace NEXT_NODE and TOKEN_URL_FROM_THE_SUMMARY; `client_id` / `client_secret` are `test_variables` placeholders, never real secrets). Every other tool's hook then sends `Authorization: Bearer <access_token>`.
- If a token endpoint is documented only in the documents (a path, form fields, `expires_in`), fetch the token ONCE at the start of the call in an `api_request` node (or code node
  that cannot raise), store it in `access_token` and its lifetime in a variable; if the fetch fails, continue and still send the header (a test environment may
  not check it). The credentials come from call/context variables or placeholders declared in `test_variables`; never invent secrets, never print them.
- On 401 with a token: fetch a new one and retry once, as the documents say.

## 3. Response envelope and errors
- The engine wraps the API body again: the API's JSON is `result["data"]`; an API that has its own `data` / `result` objects is read as `data.data.<field>` and
  `data.result.<field>`. Use the documents' success rule (for example a return code field) in the post-hook: success is HTTP 200 AND that rule; anything else is an error.
- Error answers may carry no `data` at all: guard every read and write a fallback for each variable a later step reads.
- Messages meant for logs (`messageText` and the like) are never read to the caller; spoken sentences are the agent's own, in the call's language.
- Distinguish "a field/block is missing" from "present with a zero/none value" exactly as the documents do; never invent a value for a missing block.
