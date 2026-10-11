"""REPLAY: run one DEV case of a compiled set with the REAL customer turns of a recorded Freya call instead of a simulated customer.

    python3 scripts/replay_turns.py --set m1 --brief f3-kestrel --case F3-003 --turns out/template_cc/eval/dev_transcripts/f3-kestrel/F3-003.p6r1.json [--stop-after verify_identity]

The recorded `user` messages are fed in order (the last one repeats if the agent asks again). No customer model, no judge: the agent
(Sonnet via claude_cli, like local_sim) is the only model, so it counts as one conversation of the shared local-sim budget. DEV cases only.
Prints the agent lines, the identity tool calls the bank saw and the nodes visited; exit 0 when the bank accepted verify_identity.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import local_sim as L  # noqa: E402
from builder.agentic.localsim.engine import Engine  # noqa: E402


def recorded_user_turns(path):
    d = json.loads(Path(path).read_text())
    out = []
    for m in d["messages"]:
        if m.get("role") == "user":
            t = (m.get("message") or m.get("text") or "").strip()
            t = t.split("\n")[-1].strip() if t.startswith("thought") else t   # a model "thought" prefix is not speech
            if t:
                out.append(t)
    return out


def replay(workflow, case, config, bank, turns, max_turns=12):
    V = L.vendor()
    session = bank.open_session(L.TEAM, case["id"])
    variables = session["variables"]

    def bank_call(name, body):
        handler = V["mockbank"].HANDLERS.get(name)
        if handler is None:
            return 404, {"ok": False, "error": f"unknown tool {name}"}
        body = dict(body or {})
        target = bank.session_for(str(body.get("customer_id") or "")) or session
        with bank.lock:
            return handler(target, body, config)

    model = L.ClaudeModel()
    engine = Engine(workflow, dict(variables), bank_call, model)
    lines, error = [], None
    try:
        first = engine.start()
        lines.append(("agent", first))
        for i in range(max_turns):
            if engine.ended:
                break
            say = turns[min(i, len(turns) - 1)] if i < len(turns) else turns[-1]
            lines.append(("customer", say))
            said = engine.user_says(say)
            lines.append(("agent", said))
            if not said and not engine.ended:
                break
            if any(c["tool"] == "get_account" for c in bank.ledger(L.TEAM, variables["customer_id"]).get("calls") or []):
                break    # identity is past: the part the recorded turns cover is done
        engine.finish()
    except L.LimitHit:
        raise
    except Exception as e:  # noqa: BLE001
        error = repr(e)[:300]
    ledger = bank.ledger(L.TEAM, variables["customer_id"])
    calls = ledger.get("calls") or []
    ver = [c for c in calls if c["tool"] == "verify_identity"]
    nodes = [json.loads(e["message"])["node"] for e in engine.events if e["role"] == "system" and '"node_enter"' in e["message"]]
    return {"lines": lines, "verify_calls": ver, "get_account": any(c["tool"] == "get_account" for c in calls), "nodes": nodes, "error": error,
            "agent_model_calls": model.calls}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", required=True)
    ap.add_argument("--brief", required=True)
    ap.add_argument("--case", required=True)
    ap.add_argument("--turns", required=True, help="a dev_transcripts/<brief>/<case>.<tag>.json file (real Freya call)")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    L.llm.load_env()
    cases, config = L.sources(a.brief)
    dev = L.dev_cases(cases, 10, 0)
    case = next((c for c in dev if c["id"] == a.case), None)
    if case is None:
        print(f"refused: {a.case} is not a DEV case of {a.brief}", file=sys.stderr)
        return 2
    wf = json.loads((L.REPO / "out" / "template_cc" / a.set / a.brief / "workflow.json").read_text())
    wf = wf.get("workflow", wf)
    bank = L.vendor()["mockbank"].Bank(dev, config)
    turns = recorded_user_turns(a.turns)
    with L.Slot():
        if L.budget_claim() is None:
            print("cap reached"); return 3
        try:
            r = replay(wf, case, config, bank, turns)
        except L.LimitHit as e:
            L.STOP.set(str(e)[:120]); print("STOP: claude limit warning:", e); return 4
    for who, t in r["lines"]:
        print(f"{who[0]} | {t}")
    print("verify_identity calls:", [(c.get("args") or c.get("request"), c.get("ok", c.get("result"))) for c in r["verify_calls"]])
    print("nodes:", " > ".join(r["nodes"]), "| get_account:", r["get_account"], "| error:", r["error"])
    if a.out:
        Path(a.out).write_text(json.dumps(r, indent=1, default=str))
    return 0 if r["get_account"] else 1


if __name__ == "__main__":
    sys.exit(main())
