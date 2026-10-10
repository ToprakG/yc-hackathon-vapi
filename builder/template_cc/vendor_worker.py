"""Play T-CC's own cases against a published workflow with build-the-builder's chat driver (run as a script).

    python vendor_worker.py --vendor <repo> --job job.json --out results.json

job.json: {"workflow_id", "origin" (the mock bank's public URL), "cases": [...], "reps": n, "concurrency": n}
For each case and rep: open a bank session, play the vendor's LLM customer (persona_for + customer_reply) against the
workflow over the chat API, read the bank ledger, score it with score_ledger, and judge the conversation with the
vendor decision-model judge (judge_transcript). Writes one row per case and rep, with the transcript and tool calls.
Runs in its own process because the vendor modules use generic names (freya, score, judge).
"""
import argparse
import json
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CLOSE_WAIT_S = 20


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vendor", required=True)
    ap.add_argument("--job", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    root = Path(a.vendor).resolve()
    for p in (root, root / "tools", root / "tools" / "driver"):
        sys.path.insert(0, str(p))
    import freya
    from chat_driver import MAX_TURNS, bank_call, chat_turn, customer_reply, for_judge
    from judge import judge_transcript
    from run_cases import persona_for
    from score import score_ledger

    job = json.loads(Path(a.job).read_text())
    wid, origin = job["workflow_id"], job["origin"].rstrip("/")

    def closed(ledger):
        calls = ledger.get("calls") or []
        return bool(calls) and calls[-1].get("tool") == "close_call" and (calls[-1].get("result") or {}).get("ok") is True

    def play(case, rep):
        row = {"case_id": case["id"], "rep": rep, "passed": False, "failed_reasons": [], "transcript": [], "tool_calls": []}
        try:
            status, opened = bank_call(origin, "/v1/practice/sessions", {"case": case["id"]})
            if status != 200:
                raise RuntimeError(f"bank session -> {status} {opened}")
            variables = opened["variables"]
            prompt = persona_for(case, {"identity": case["identity"]}, case.get("style"))["prompt"]
            prompt += ("\n\nWHEN YOU NAME A TIME: say the hour and the minutes, like 11:00. Do not say morning, "
                       "afternoon, or around in place of that time.")
            call_id, agent, _ = chat_turn(wid, "Hello?", variables)
            agent_lines, customer_lines = ([agent] if agent else []), []
            for _ in range(MAX_TURNS):
                if not agent_lines:
                    break
                reply = customer_reply(prompt, agent_lines, customer_lines)
                customer_lines.append(reply)
                call_id, agent, _ = chat_turn(wid, reply, variables, call_id)
                if agent:
                    agent_lines.append(agent)
                _, ledger = bank_call(origin, "/v1/practice/ledger/" + variables["customer_id"])
                if closed(ledger) or not agent:
                    break
            try:
                freya.api("POST", "/api/v2/chat/end", {"callId": call_id})
            except Exception:
                pass
            t0 = time.time()  # the close record is a lifecycle tool: it lands after the chat ends
            while True:
                _, ledger = bank_call(origin, "/v1/practice/ledger/" + variables["customer_id"])
                if closed(ledger) or time.time() - t0 > CLOSE_WAIT_S:
                    break
                time.sleep(2)
            scored = score_ledger(case, ledger)
            messages = []
            if call_id:
                try:
                    messages = freya.get_call(call_id).get("messages") or []
                except Exception:
                    messages = []
            judged = (judge_transcript(for_judge(messages), case) if messages
                      else {"pass": None, "status": "no_transcript", "checks": []})
            failed = list(scored["failed"])
            for c in judged.get("checks") or []:
                if c.get("answer") != "yes":
                    failed.append(f"conversation: {c.get('check')} (answer {c.get('answer')}, p={c.get('p')})")
            if judged.get("pass") is None and judged.get("status") not in ("ok",):
                failed.append(f"conversation: judge status {judged.get('status')}")
            row.update(passed=bool(scored["pass"]) and judged.get("pass") is True, failed_reasons=failed,
                       call_id=call_id, judge_status=judged.get("status"),
                       tool_calls=[{"tool": c.get("tool"), "args": c.get("args"), "result": c.get("result")}
                                   for c in ledger.get("calls") or []],
                       transcript=[{"role": m.get("role"), "text": m.get("message") or m.get("content") or ""}
                                   for m in for_judge(messages) if m.get("role") in ("assistant", "user")])
        except Exception as e:  # noqa: BLE001 - one broken case is a failed case, not a broken run
            row["failed_reasons"] = [f"runner error: {e!r}"]
            row["error"] = traceback.format_exc(limit=3)
        return row

    jobs = [(c, r) for c in job["cases"] for r in range(1, int(job.get("reps", 1)) + 1)]
    with ThreadPoolExecutor(max_workers=int(job.get("concurrency", 4))) as pool:
        rows = list(pool.map(lambda cr: play(*cr), jobs))
    Path(a.out).write_text(json.dumps(rows, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
