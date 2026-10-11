"""Live simulation dashboard: http://127.0.0.1:8901 (refreshes every 5 s). READ-ONLY: it never starts, cancels or changes anything.

Shows (1) the Freya API health and the newest simulations of the workspace, with the per-run state of the running one (queued / running /
analyzing / finished) and a "possibly stuck" flag, (2) the m1 GATE against p6 per brief (from the shared result files, pass/fail only - the
sealed details are never read), the gate's try counts and its log tail, (3) the processes that run evals.

    .venv310/bin/python scripts/sim_dashboard.py [--port 8901]
"""
import argparse
import collections
import datetime
import html
import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
EVAL = REPO / "out/template_cc/eval"
BRIEFS = ["brief-a", "brief-b", "f1-nordhavn", "f2-ostral", "f3-kestrel", "f4-brightwell", "f5-halden-email", "f6-corvid-memo", "f7-lumen-codes"]
STATE = {"freya": {"ok": None, "error": None, "at": 0, "sims": []}}
LOCK = threading.Lock()


def load_env():
    for line in (REPO / ".env").read_text().splitlines():
        line = line.strip().removeprefix("export ")
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            if v.strip() and not os.environ.get(k.strip()):
                os.environ[k.strip()] = v.strip().strip("\"'")


def poll_freya():
    """Background thread: the newest simulations (+ run states of a running one) every 10 s. A failing call only shows up as the error."""
    import freya  # noqa: PLC0415
    while True:
        res = {"ok": False, "error": None, "at": time.time(), "sims": []}
        try:
            r = freya.api("GET", "/api/v2/simulations", workspaceId=freya.workspace_id(), limit=8)
            now = datetime.datetime.now(datetime.timezone.utc)
            for s in (r.get("simulations") or r.get("items") or r):
                created = datetime.datetime.fromisoformat(s["createdAt"].replace("Z", "+00:00"))
                m = s.get("metrics") or {}
                row = {"id": s["id"][:8], "name": s["name"], "status": s["status"], "age": round((now - created).total_seconds() / 60, 1),
                       "created": created.astimezone().strftime("%H:%M:%S"), "total": m.get("totalRuns"), "passed": m.get("passedRuns"),
                       "failed": m.get("failedRuns"), "runs": None}
                if s["status"] == "running":
                    try:
                        its = freya.api("GET", f"/api/v2/simulations/{s['id']}/iterations")
                        its = its.get("iterations") or its.get("items") or its
                        runs = freya.get_iteration(s["id"], its[0]["id"])["runs"]
                        c = collections.Counter(str(x.get("outcome") or x.get("status")) for x in runs)
                        row["runs"] = dict(c)
                        row["stuck"] = (row["age"] > 20) or (row["age"] > 3 and set(c) == {"queued"})
                    except Exception as e:  # noqa: BLE001
                        row["runs"] = {"error": str(e)[:60]}
                res["sims"].append(row)
            res["ok"] = True
        except Exception as e:  # noqa: BLE001
            res["error"] = str(e)[:160]
        with LOCK:
            STATE["freya"] = res
        time.sleep(10)


def results(tag):
    out = {}
    for f in (EVAL / "freya").glob(f"*.{tag}.json"):
        try:
            d = json.loads(f.read_text())
            out[d["brief"]] = (d["passed"], d["cases"])
        except Exception:  # noqa: BLE001
            pass
    return out


def procs():
    r = subprocess.run(["ps", "-axo", "pid,etime,command"], capture_output=True, text=True).stdout.splitlines()
    keep = [l for l in r if re.search(r"tcc_eval_freya\.py|run_cases\.sh|gate_m1\.sh|eval_chain\.sh|selftest_run", l) and "grep" not in l and "timeout " not in l]
    return [" ".join(l.split())[:150] for l in keep]


def gate():
    m, p = results("m1g1"), results("p6g1")
    running = {m_.group(1) for l in procs() for m_ in [re.search(r"--brief (\S+).*--tag m1g1", l)] if m_}
    rows = []
    for b in BRIEFS:
        tries = (EVAL / "gate_m1.state" / f"{b}.tries")
        t = int(tries.read_text()) if tries.exists() else 0
        status = "done" if b in m else "running" if b in running else "abandoned" if (EVAL / "gate_m1.state" / f"{b}.abandoned").exists() else "waiting"
        rows.append({"brief": b, "m1": m.get(b), "p6": p.get(b), "tries": t, "status": status})
    done = [r for r in rows if r["m1"]]
    log = (EVAL / "gate_m1.log").read_text().splitlines()[-14:] if (EVAL / "gate_m1.log").exists() else []
    return {"rows": rows, "m1_total": sum(r["m1"][0] for r in done), "m1_cases": sum(r["m1"][1] for r in done),
            "p6_same": sum((r["p6"] or (0, 0))[0] for r in done), "p6_all": sum(v[0] for v in p.values()), "log": log, "done": len(done)}


def state():
    with LOCK:
        f = dict(STATE["freya"])
    f["stale_s"] = round(time.time() - f["at"]) if f["at"] else None
    return {"now": time.strftime("%H:%M:%S"), "freya": f, "gate": gate(), "procs": procs()}


PAGE = """<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Simulations</title>
<style>
:root{--bg:#fff;--fg:#1a1a1a;--mut:#666;--line:#ddd;--ok:#1a7f37;--bad:#cf222e;--warn:#9a6700;--card:#f6f8fa}
@media(prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--mut:#8b949e;--line:#30363d;--ok:#3fb950;--bad:#f85149;--warn:#d29922;--card:#161b22}}
body{font:14px/1.45 system-ui,sans-serif;background:var(--bg);color:var(--fg);margin:0;padding:16px;max-width:1100px}
h1{font-size:18px;margin:0 0 4px}h2{font-size:14px;margin:18px 0 6px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;font-variant-numeric:tabular-nums}
.card{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:8px 12px;margin:6px 0}
.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}.mut{color:var(--mut)}pre{margin:0;white-space:pre-wrap;font-size:12px}
.banner{padding:8px 12px;border-radius:6px;margin:8px 0;border:1px solid var(--bad);color:var(--bad)}
</style></head><body><h1>Simulations <span class=mut id=t></span></h1><div id=app>loading...</div>
<script>
const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const cls=s=>({done:'ok',completed:'ok',running:'warn',abandoned:'bad',waiting:'mut'}[s]||'');
async function tick(){try{const d=await (await fetch('/api/state')).json();const f=d.freya,g=d.gate;let h='';
 if(f.ok===null)h+=`<div class=banner>Freya API: no answer yet - a call can hang for up to 2 minutes during an outage</div>`;else h+=f.ok?`<div class=card>Freya API <b class=ok>answers</b> <span class=mut>(checked ${f.stale_s}s ago)</span></div>`:`<div class=banner>Freya API <b>failing</b>: ${esc(f.error)} <span class=mut>(${f.stale_s}s ago)</span></div>`;
 const stuck=(f.sims||[]).filter(s=>s.stuck);if(stuck.length)h+=`<div class=banner>Possibly stuck: ${stuck.map(s=>esc(s.name)+' ('+s.id+', '+s.age+' min, '+JSON.stringify(s.runs)+')').join('; ')}</div>`;
 h+='<h2>Newest simulations</h2><table><tr><th>id<th>name<th>status<th>created<th>age<th>runs<th>passed<th>live run states</tr>';
 for(const s of f.sims||[])h+=`<tr><td>${s.id}<td>${esc(s.name)}<td class=${cls(s.status)}>${s.status}<td>${s.created}<td>${s.age} min<td>${s.total??''}<td>${s.passed??''}<td>${s.runs?esc(JSON.stringify(s.runs)):''}</tr>`;
 h+='</table><h2>m1 gate vs p6 (GATE cases, pass/fail only)</h2><table><tr><th>brief<th>m1 (m1g1)<th>p6 (p6g1)<th>status<th>tries</tr>';
 for(const r of g.rows)h+=`<tr><td>${r.brief}<td>${r.m1?r.m1[0]+'/'+r.m1[1]:'-'}<td>${r.p6?r.p6[0]+'/10':'-'}<td class=${cls(r.status)}>${r.status}<td>${r.tries}</tr>`;
 h+=`</table><div class=card><b>${g.done}/9 briefs done.</b> m1 <b>${g.m1_total}/${g.m1_cases}</b> vs p6 <b>${g.p6_same}</b> on the same briefs <span class=mut>(p6 total over all 9: ${g.p6_all}/90; rule: ship m1 if m1 >= p6 over all 9)</span></div>`;
 h+='<h2>Gate log</h2><div class=card><pre>'+esc(g.log.join('\\n'))+'</pre></div><h2>Eval processes</h2><div class=card><pre>'+esc(d.procs.join('\\n')||'none')+'</pre></div>';
 document.getElementById('app').innerHTML=h;document.getElementById('t').textContent=d.now}catch(e){document.getElementById('app').innerHTML='<div class=banner>dashboard server not answering</div>'}}
tick();setInterval(tick,5000);
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/state"):
            body, ctype = json.dumps(state()).encode(), "application/json"
        else:
            body, ctype = PAGE.encode(), "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8901)
    a = ap.parse_args()
    load_env()
    threading.Thread(target=poll_freya, daemon=True).start()
    print(f"simulation dashboard: http://127.0.0.1:{a.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()
