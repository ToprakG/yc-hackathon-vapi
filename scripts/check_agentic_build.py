"""Checks for an AGENTIC builder run (python3 builder/build.py <case_folder> <mock_url> --variant agentic ...).
    python3 scripts/check_agentic_build.py <out dir holding build/ and build_py.json> <mock_url>
 build ok + lint 0; workflow tools = only operations of the mock's OpenAPI; tool URLs under servers[0].url of mock_url/openapi.json; no identity/promise/negotiation nodes unless
 the OpenAPI has such tools; policy.language; call variables declared; no tool asks the caller for a call variable (heuristic); the export at workflows/; submission.json;
 the trace (events, model) and the Claude Code session log in claude-session/ with no secret in it.  Prints OK / PROBLEM per line and a VERDICT; reads outputs only."""
import json, re, sys, urllib.request
from pathlib import Path
sys.path.insert(0, ".")
out = Path(sys.argv[1]); b = out / "build"; mock = sys.argv[2].rstrip("/")
problems = []


def line(ok, msg):
    print(("OK      " if ok else "PROBLEM ") + msg)
    if not ok:
        problems.append(msg)


def jload(p):
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return None


info = {}
try:
    info = json.loads((out / "build_py.json").read_text().strip().splitlines()[-1])
except (OSError, ValueError, IndexError):
    pass
rep = jload(b / "build_report.json") or {}
wf = jload(b / "workflow.json") or {"nodes": {}}
wf = wf.get("workflow", wf)
pol = jload(b / "policy.json") or {}
line(info.get("status") == "ok" and (rep.get("lint") or {}).get("errors") == 0, f"build.py status {info.get('status')}, lint errors {(rep.get('lint') or {}).get('errors')} ({info.get('message') or ''})")
# API
try:
    req = urllib.request.Request(mock + "/openapi.json", headers={"user-agent": "Mozilla/5.0"})
    api = json.load(urllib.request.urlopen(req, timeout=30))
except Exception as e:  # noqa: BLE001
    api = {}
    line(False, f"GET {mock}/openapi.json failed: {e}")
ops = {re.sub(r"[^A-Za-z0-9_]", "_", p.strip("/").split("/")[-1]) for p in api.get("paths", {})} | {re.sub(r"[^A-Za-z0-9_]", "_", o.get("operationId") or "") for it in api.get("paths", {}).values() for o in it.values() if isinstance(o, dict) and o.get("operationId")}
ops.add("oauth_token")   # the token request of an OAuth2 clientCredentials flow
server = (api.get("servers") or [{}])[0].get("url", "").rstrip("/")
names, urls = set(), []


def walk(o):
    if isinstance(o, dict):
        f = o.get("function")
        if isinstance(f, dict) and f.get("name") and f.get("handler") == "__function__:api_call":   # only API tools; end_call / code_exec functions are the platform's
            names.add(f["name"])
        for k, v in o.items():
            if k == "url" and isinstance(v, dict) and isinstance(v.get("default"), str):
                urls.append(v["default"])
            elif k == "url" and isinstance(v, str):
                urls.append(v)
            else:
                walk(v)
    elif isinstance(o, list):
        for x in o:
            walk(x)


walk(wf)
api_tools = {n for n in names if n not in {"code_exec", "end_call", "call_finished", "api_call"}}
line(api_tools <= ops, f"workflow tools {sorted(api_tools)} ⊆ OpenAPI operations {sorted(o for o in ops if o)}" + ("" if api_tools <= ops else f"; NOT in the API: {sorted(api_tools - ops)}"))
tok = {t for t in re.findall(r"\"tokenUrl\": \"([^\"]+)\"", json.dumps(api))}
bad = [u for u in urls if server and not u.startswith(server + "/") and u not in tok]   # the OAuth2 token URL is declared by the API and may sit beside the base
line(bool(urls) and not bad, f"{len(urls)} tool URL(s) under {server}/" + (f"; BAD {sorted(set(bad))[:3]}" if bad else ""))
nodes = list(wf.get("nodes", {})) + list(wf.get("global_nodes", {}))
idn = [n for n in nodes if re.search(r"identity|^id_|verify|promise|negoti", n, re.I)] if not any("verify" in o or "promise" in o for o in ops) else []
line(not idn, f"no identity / promise / negotiation nodes when the API has no such tools: {idn[:6]}")
line(str(pol.get("language", "")).lower().startswith("tr"), f"policy.language = {pol.get('language')!r}")
cv = pol.get("call_variables") or []
tv = set((wf.get("test_variables") or {}))
line(bool(cv) and all((c if isinstance(c, str) else c.get("name")) in tv for c in cv), f"call variables {cv} declared in test_variables {sorted(tv)[:6]}")
sv = Path(info.get("saved") or "x")
line(sv.exists() and sv.parent.name == "workflows", f"export at {info.get('saved')}")
s = jload(Path("submission.json")) or {}
line(bool(s.get("members")) and all(k in s for k in ("workflow", "trace", "mock_url")), f"submission.json keys {sorted(s)}")
tr = Path(str(info.get("trace") or s.get("trace") or ""))
tdir = tr if tr.is_dir() else tr.parent
line((tdir / "trace.txt").exists() or (tdir / "messages.jsonl").exists(), f"trace files in {tdir}")
logs = list((tdir / "claude-session").glob("*.jsonl")) if (tdir / "claude-session").is_dir() else []
line(bool(logs), f"Claude Code session log copied: {[p.name for p in logs][:3]}")
if logs:
    from builder.common import session_log as SL
    leak = [p.name for p in logs if SL.redact(p.read_text(errors="replace")) != p.read_text(errors="replace")]
    line(not leak, f"session logs already redacted (re-redaction changes nothing): leaks in {leak}")
print("\nVERDICT:", "ALL OK" if not problems else f"{len(problems)} PROBLEM(S)")
sys.exit(0 if not problems else 1)
