# Bank mock spec (JSON) — contract between the converter (S3) and the Worker (S2)

One spec = one tenant. The Worker serves it at `https://<worker>/<tenant>/…`. Put specs in `mock/specs/<tenant>.json`
(bundled at deploy by `node scripts/bundle.mjs`) or upload live: `PUT /<tenant>/admin/spec` (Bearer ADMIN_TOKEN).

```jsonc
{
  "tenant": "brief-a",                 // url segment; [a-z0-9-]
  "info": {"title": "...", "version": "...", "description": "..."},   // for /openapi.json
  "base_path": "/v1",                  // tool calls are POST /<tenant><base_path><endpoint.path>
  "identity": {                        // used by op verify_identity
    "fields": [                        // each field is one security question
      {"name": "date_of_birth", "kind": "date"},   // kind: date (YYYY-MM-DD, words/other formats normalised) | digits (strip non-digits; optional "len") | text (case-insensitive)
      {"name": "phone_last4",  "kind": "digits", "len": 4}
    ],
    "max_wrong": 3,                    // wrong answers in total (all fields) end the check
    "swap_hint": true                  // date answer = truth with day/month swapped → response "hint":"day_month_swapped" (still a wrong answer)
  },
  "products": {                        // op get_account output = customer.products mapped with this table
    "id_prefix": "p",                  // product_id when the seed product has none: p1, p2 ...
    "map": {"type": "type", "card_last4": "card_ending", "past_due": "overdue_amount", "days_late": "days_past_due", "minimum_payment": "min_due", "instalment_amount": "instalment_amount"}
                                       // output key → seed product key. Missing seed key → output key omitted.
  },
  "rules": {"one_promise_per_product": true, "require_verified": ["get_account", "create_promise", "add_note"]},
  "endpoints": [
    {"op": "verify_identity", "method": "POST", "path": "/verify_identity", "summary": "...",
     "params": {"answer": "answer"},   // optional: canonical param name → actual request field name (default identical)
     "request":  {"type": "object", "properties": {...}, "required": [...]},   // JSON schema, copied from the source openapi; also used to validate the call (required, enum, type, format date)
     "responses": {"200": {...}, "500": {...}}}                                  // copied to /openapi.json as is
  ],
  "customers": [                       // seed data
    {"customer_id": "c_001", "identity": {"date_of_birth": "1985-03-14", "phone_last4": "0311"},
     "products": [{"type": "credit_card", "card_ending": "7710", "overdue_amount": 725.0, "days_past_due": 9, "min_due": 181.0}],
     "meta": {}}                       // meta is free (case id, expected outcome ...), echoed by /state
  ],
  "faults": [{"op": "schedule_callback", "customer_id": null, "times": 1, "status": 500}]   // optional failure injection; customer_id null = every customer
}
```

## Ops (endpoint.op)
`verify_identity` `get_account` `create_promise` `add_note` `schedule_callback` `transfer_to_agent` `close_call` `dispute` and the
generic `record` (any other endpoint: validated against `request`, stored under `kind` = endpoint.kind or path).
Canonical params: customer_id field answer product_id amount date time reason text queue outcome.
Error strings follow the organisers' mock: `identity not verified`, `unknown customer`, `call already closed`, `too many wrong answers`.
Every call is written to the ledger; a call that hits a fault (HTTP 500) is not.

## Read side (organisers/scorer)
`GET /<tenant>/openapi.json`  generated from the spec (servers = this Worker)
`GET /<tenant>/records[?customer_id=&limit=]`  the full ledger, oldest first
`GET /<tenant>/ledger/<customer_id>`  one call in scorer shape `{outcome, reason, promises, notes, callbacks, transfers, disputes, calls}`
`GET /<tenant>/state`  customers with verification/close state
Admin (needs `ADMIN_TOKEN` secret): `GET|PUT /<tenant>/admin/spec`, `PUT /<tenant>/admin/customers` (merge by customer_id), `POST /<tenant>/admin/reset[?customer_id=]`.
Optional `RECORDS_TOKEN` secret: if set, read side needs `Authorization: Bearer …` or `?token=`.
