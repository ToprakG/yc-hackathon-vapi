# Kasko hasar ihbarı domain

- `sop.md` — call-center SOP (Turkish). This is the task text the builder reads.
- `tools.json` — `verify_identity`, `get_policy`, `create_claim`, `transfer_to_human` as `ToolDef`s.
- `policies.json` — 6 synthetic customers (fake TCKNs).
- `tools_server.py` — FastAPI mock of the tools. `get_policy` and `create_claim` fail unless
  `verify_identity` succeeded in the same session.

## Run the mock tools

```bash
.venv/bin/uvicorn agentforge.domain.kasko.tools_server:app --port 8001
cloudflared tunnel --url http://localhost:8001
```

Put the tunnel URL in `.env` as `TOOLS_BASE_URL` (no trailing slash). Vapi calls
`{TOOLS_BASE_URL}/tools/{name}`.

Endpoints:

- `POST /tools/{name}` — Vapi tool-call webhook (`message.toolCallList`, responds `{"results": [{"toolCallId", "result"}]}`)
  or plain JSON args (responds with the result object). Session id comes from `?session_id=`, then the Vapi
  `message.call.id`, then `message.assistant.metadata.session_id` / `metadata.session_id`, then the `X-Session-Id` header.
- `GET /calls/{session_id}` — every call in the session: `{session_id, name, args, result, timestamp}`.
- `POST /reset` — clears all sessions and logs.
