"""Summarise a bank's tool API file (OpenAPI 3) for the builder agent and for lint.

Standard library only. Handles what the final briefs may change: renamed fields, an integer cents amount,
one datetime field instead of date + time, a `close_call` that takes a single `code`, and local `$ref`s.
"""

from __future__ import annotations

import json
from pathlib import Path

KIT_TOOLS = ("verify_identity", "get_account", "create_promise", "add_note", "schedule_callback",
             "transfer_to_agent", "close_call")
READ_TOOLS = ("verify_identity", "get_account")  # the rest write data; no retries on them


def load(path: str | Path) -> dict:
    return summarize(json.loads(Path(path).read_text(encoding="utf-8")))


def _resolve(spec: dict, node, depth: int = 0):
    """Follow local `#/...` references; leave everything else as it is."""
    while isinstance(node, dict) and "$ref" in node and depth < 20:
        ref = node["$ref"]
        if not ref.startswith("#/"):
            return {}
        target = spec
        for part in ref[2:].split("/"):
            target = target.get(part.replace("~1", "/").replace("~0", "~"), {}) if isinstance(target, dict) else {}
        node, depth = target, depth + 1
    return node if isinstance(node, dict) else {}


def _field(spec: dict, prop: dict, required: bool) -> dict:
    prop = _resolve(spec, prop)
    out = {"type": prop.get("type", "string"), "required": required}
    for key in ("enum", "description", "format", "pattern", "minimum", "maximum"):
        if key in prop:
            out[key] = prop[key]
    if prop.get("type") == "array":
        items = _resolve(spec, prop.get("items", {}))
        if items.get("type") == "object" or "properties" in items:
            req = set(items.get("required", []))
            out["items"] = {k: _field(spec, v, k in req) for k, v in items.get("properties", {}).items()}
        else:
            out["items"] = {"type": items.get("type", "string")}
    elif prop.get("type") == "object" and "properties" in prop:
        req = set(prop.get("required", []))
        out["properties"] = {k: _field(spec, v, k in req) for k, v in prop["properties"].items()}
    return out


def _schema_fields(spec: dict, schema: dict) -> dict:
    schema = _resolve(spec, schema)
    req = set(schema.get("required", []))
    return {k: _field(spec, v, k in req) for k, v in schema.get("properties", {}).items()}


ENVELOPE_NAMES = {"data", "payload", "request", "body", "params", "input"}


def _envelope(spec: dict, schema: dict):
    """A request body that wraps the real fields in one required object next to call metadata ({data: {...}, call: {...}}).
    Returns (wrapper name, inner schema, other top-level property names) or None. Generic: any wrapper that is required and either
    sits beside other properties or has a conventional envelope name."""
    schema = _resolve(spec, schema)
    props, req = schema.get("properties") or {}, set(schema.get("required") or [])
    inner = {k: _resolve(spec, v) for k, v in props.items() if _resolve(spec, v).get("type") == "object" and _resolve(spec, v).get("properties")}
    for k, v in inner.items():
        if k in req and (len(props) >= 2 or k.lower() in ENVELOPE_NAMES):
            return k, v, [x for x in props if x != k]
    return None


def _security(spec: dict) -> dict:
    schemes = {}
    for name, sch in ((spec.get("components") or {}).get("securitySchemes") or {}).items():
        sch = _resolve(spec, sch)
        schemes[name] = {k: sch[k] for k in ("type", "scheme", "bearerFormat", "in", "name", "description", "flows") if k in sch}
    return {"schemes": schemes, "global": spec.get("security") or []}


def _token_flow(spec: dict, base: str):
    """An OAuth2 clientCredentials flow with a tokenUrl, if the API declares one (a relative token URL is resolved against the server's origin)."""
    from urllib.parse import urljoin  # noqa: PLC0415
    for name, sch in ((spec.get("components") or {}).get("securitySchemes") or {}).items():
        flow = ((_resolve(spec, sch).get("flows") or {}).get("clientCredentials") or {})
        if flow.get("tokenUrl"):
            url = flow["tokenUrl"] if str(flow["tokenUrl"]).startswith("http") else urljoin(base + "/", flow["tokenUrl"])
            return {"scheme": name, "tokenUrl": url, "scopes": list((flow.get("scopes") or {}).keys())}
    return None


def summarize(spec: dict) -> dict:
    servers = spec.get("servers") or [{}]
    base = str(servers[0].get("url", "")).rstrip("/")
    tools = {}
    for path, item in (spec.get("paths") or {}).items():
        for method, op in item.items():
            if method.lower() not in ("get", "post", "put", "patch", "delete") or not isinstance(op, dict):
                continue
            name = op.get("operationId") or path.strip("/").split("/")[-1]
            body = _resolve(spec, op.get("requestBody", {}))
            schema = _resolve(spec, (body.get("content", {}).get("application/json", {}) or {}).get("schema", {}))
            responses, errors, response_fields = op.get("responses", {}) or {}, {}, {}
            for status, resp in responses.items():
                resp = _resolve(spec, resp)
                if str(status).startswith("2"):
                    rs = (resp.get("content", {}).get("application/json", {}) or {}).get("schema", {})
                    response_fields = _schema_fields(spec, rs)
                    if resp.get("description"):
                        errors[str(status)] = resp["description"]
                elif resp.get("description"):
                    errors[str(status)] = resp["description"]
            env = _envelope(spec, schema)
            inner = env[1] if env else schema
            hdrs = [{"name": p_.get("name"), "required": bool(p_.get("required"))} for p_ in (op.get("parameters") or [])
                    if isinstance(_resolve(spec, p_), dict) and _resolve(spec, p_).get("in") == "header" for p_ in [_resolve(spec, p_)]]
            tools[name] = {
                "envelope": {"wrap": env[0], "other_keys": env[2]} if env else None,
                "security": op.get("security"),
                "headers": hdrs,
                "method": method.upper(),
                "path": path,
                "url": base + path,
                "summary": op.get("summary", "") or op.get("description", ""),
                "request": _schema_fields(spec, inner),
                "required": list(_resolve(spec, inner).get("required", [])),
                "response": response_fields,
                "statuses": errors,
            }
    tflow = _token_flow(spec, base)
    if tflow and "oauth_token" not in tools:   # the token request is a tool of its own: the workflow calls it once at the start of the call
        tools["oauth_token"] = {"envelope": None, "security": [], "headers": [], "method": "POST", "path": tflow["tokenUrl"], "url": tflow["tokenUrl"],
                                "summary": "OAuth2 client-credentials token request (form-encoded)", "token_flow": tflow,
                                "request": {"grant_type": {"type": "string", "required": True, "enum": ["client_credentials"]},
                                            "client_id": {"type": "string", "required": True}, "client_secret": {"type": "string", "required": True}},
                                "required": ["grant_type", "client_id", "client_secret"],
                                "response": {"access_token": {"type": "string", "required": True}, "expires_in": {"type": "integer", "required": False}}, "statuses": {}}
    return {"security": _security(spec), "token_flow": tflow, "base_url": base, "title": (spec.get("info") or {}).get("title", ""), "tools": tools,
            "missing_kit_tools": [t for t in KIT_TOOLS if t not in tools]}


def _fmt_field(name: str, f: dict, indent: str = "    ") -> list[str]:
    bits = [f["type"] + ("" if not f.get("format") else f"({f['format']})"), "required" if f.get("required") else "optional"]
    if "enum" in f:
        bits.append("enum=" + "|".join(map(str, f["enum"])))
    line = f"{indent}{name}: {', '.join(bits)}"
    if f.get("description"):
        line += f" -- {f['description']}"
    lines = [line]
    for sub, sf in (f.get("items") or f.get("properties") or {}).items():
        if isinstance(sf, dict):  # an array of scalars has items={"type": "string"}: no dict values
            lines += _fmt_field(sub, sf, indent + "    ")
    return lines


def render(summary: dict, max_chars: int = 14000) -> str:
    """Compact text for the agent: one block per tool."""
    out = [f"base URL: {summary['base_url']}"]
    sec = summary.get("security") or {}
    tf = summary.get("token_flow")
    if tf:
        out.append(f"TOKEN FLOW: scheme {tf['scheme']} is OAuth2 client credentials; POST {tf['tokenUrl']} (form-encoded grant_type, client_id, client_secret) ONCE at the start of the call "
                   "with templates/token_step_node.json (tool 'oauth_token' below), store access_token, and send 'Authorization: Bearer <access_token>' on every other tool.")
    for name, sch in (sec.get("schemes") or {}).items():
        out.append(f"AUTH scheme {name}: {sch}  (global requirement: {sec.get('global') or 'none declared'}) -> send it on every tool call (see reference/envelope-and-auth.md)")
    if summary["missing_kit_tools"] and len(summary["missing_kit_tools"]) < len(KIT_TOOLS):   # only for a kit-shaped API; an API that has none of the kit tools is not missing them
        out.append("MISSING kit tools: " + ", ".join(summary["missing_kit_tools"]))
    for name, t in summary["tools"].items():
        out.append(f"\n{name}  {t['method']} {t['url']}")
        if t.get("envelope"):
            out.append(f"  ENVELOPE: the request fields below go inside the object '{t['envelope']['wrap']}' of the JSON body; other top-level keys: {t['envelope']['other_keys'] or 'none'} (see reference/envelope-and-auth.md)")
        if t.get("headers"):
            out.append("  headers: " + ", ".join(h["name"] + ("*" if h["required"] else "") for h in t["headers"] if h.get("name")))
        if t["summary"]:
            out.append(f"  summary: {t['summary']}")
        out.append("  request:")
        for fname, f in t["request"].items():
            out += _fmt_field(fname, f)
        if t["response"]:
            out.append("  response (data.*):")
            for fname, f in t["response"].items():
                out += _fmt_field(fname, f)
        for status, desc in t["statuses"].items():
            out.append(f"  {status}: {desc}")
    text = "\n".join(out)
    return text if len(text) <= max_chars else text[:max_chars] + "\n... (truncated)"


if __name__ == "__main__":
    import sys

    print(render(load(sys.argv[1])))
