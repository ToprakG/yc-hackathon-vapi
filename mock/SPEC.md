# mock spec (JSON) — contract between the converter (S3, `mock/convert.py`) and the Worker (S2)

One file per bank: `mock/spec.<id>.json`.

```
{
  "spec_version": 1,
  "id": "brief-a", "name": "Freya Bank",
  "config":   { ... },   // the CANONICAL bank config (same schema as testbed/fake_briefs/*/config.json and vendor/.../seed/policy_ab.py:POLICY_A)
  "openapi":  { ... },   // the service contract as OpenAPI 3; served verbatim at GET /openapi.json (paths/field names are the bank's own)
  "customers": [         // seed accounts; identical shape to a testbed case minus script/expected
    { "customer_id": "c_ab12cd34",
      "variables": {"first_name": "Daniel", "last_name": "Reyes", "title": "Mr", "now": "2026-10-14T11:00"},
      "identity":  {"date_of_birth": "1988-03-14", "phone_last4": "4471"},        // keys = config.identity.questions
      "products":  [{"type": "credit_card", "card_last4": "4821", "past_due": 420.0, "days_late": 6, "minimum_payment": 126.0}] }
  ]
}
```

## What the Worker reads from `config` (all keys optional unless marked; defaults = Brief A)
- `tools.<tool>`: the request field names the bank uses. `verify_identity {field, answer}`; `create_promise {product_id, amount, date}`;
  `schedule_callback {mode: "datetime"|"date_time", datetime | date,time}`; `close_call {mode: "outcome_reason"|"code", outcome, reason | code}`;
  `transfer_to_agent {queue}`; `add_note {product_id, reason}`.
- `account_fields {product_id, type, past_due, days_late}`, `product_id_format` ("p{n}"), `product_types.*.floor_field`.
- `identity {questions[], max_wrong, swap_hint}`; `callback {start, end, same_day}`; `holidays[]`.
- `outcome_map` (key -> [outcome, reason]), `queue_map`, `note_map` — the ledger reports canonical keys (see mockbank.py docstring).
- Behaviour to port: vendor/build-the-builder/tools/driver/mockbank.py (`Bank`, `HANDLERS`): identity (date swap hint, max_wrong lock), get_account (verified only), create_promise (dates/amount checks, per-product),
  add_note, schedule_callback (window), transfer_to_agent, close_call (once), ledger. Dispute = add_note with the dispute reason.

## Endpoints the Worker serves
`POST /<tool>` for the 7 tools (paths as in `openapi.paths`), `GET /openapi.json`, `GET /records` (ledger per customer: promises, notes, callbacks, transfers, outcome, reason; `GET /records/<customer_id>`), `GET /customers` (seed ids, no secrets).
State per customer (session) lives in KV / Durable Object; the seed is read from the spec at deploy.

Validate a spec with `python3 mock/convert.py --check mock/spec.<id>.json`.
