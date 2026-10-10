"""TEST_PLAN section 4: search and optimisation. Overnight only, then about 2 hours of confirmation in the morning.

Agent paths take `{brief}` (each brief has its own V1).

python -m agentforge.experiments.section4 gepa run --best 'runs/col-{brief}-v1/agent.json' --practice practice --budget 3000
    Requires judge agreement >= 90% (T0.3 branch "local+gepa"); --force skips that check for dry runs. Resumable.
python -m agentforge.experiments.section4 gepa confirm --best ... --practice practice [--platform freya] [--top 3]
    Top 3 candidates through the gate on Freya. A winner's rules are merged into the template. If local scores rose but
    no candidate wins on Freya, the judge and Freya disagree: GEPA is dropped.
python -m agentforge.experiments.section4 aflow --best ... --practice practice
    Only if T1.7 chose a workflow. Each hand-made shape vs the single-prompt agent, then one LLM edit of the best shape.
python -m agentforge.experiments.section4 lessons mine --runs runs/<label>/<practice>_*.jsonl [--min-count 3]
python -m agentforge.experiments.section4 lessons test --best ... --practice practice
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agentforge.build.addons import apply_addons, load_locked_rules, lock_rules, lock_workflow
from agentforge.config import RUNS_DIR
from agentforge.domain.collections import brief_dir, list_briefs, load_personas, load_policy
from agentforge.experiments.col_common import dump, results_dir
from agentforge.experiments.paired import agents_for, gate, report
from agentforge.experiments.section2 import failure_clusters
from agentforge.optimize import aflow, gepa, lessons
from agentforge.schemas import AgentConfig, ScoredRun
from agentforge.store import load_jsonl, save_json

GEPA_BRANCH = "local+gepa"


def state_path() -> Path:
    return results_dir("_all", "section4") / "gepa_state.json"


def with_rules(best: dict[str, AgentConfig], rules: list[str], suffix: str) -> dict[str, AgentConfig]:
    out = {}
    for brief, cfg in best.items():
        variant = apply_addons(cfg, load_policy(brief_dir(brief)), [], label=f"{cfg.version_label}+{suffix}", rules=rules)
        save_json(RUNS_DIR / variant.version_label / "agent.json", variant)
        out[brief] = variant
    return out


def judge_branch(practice: str) -> str | None:
    path = results_dir(practice, "judge") / "agreement.json"
    return json.loads(path.read_text()).get("branch") if path.exists() else None


# --- GEPA-lite --------------------------------------------------------------------------------------------------


def gepa_run(best: dict[str, AgentConfig], practice: str, budget: int, platform: str, runs: int, minibatch: int,
             resume: bool, force: bool) -> dict:
    branch = judge_branch(practice)
    if branch != GEPA_BRANCH and not force:
        raise SystemExit(f"GEPA needs judge agreement >= 90% (T0.3 branch '{GEPA_BRANCH}'); current branch: {branch}. "
                         "Run experiments.agreement first, or --force for a dry run.")
    path = state_path()
    if resume and path.exists():
        state = gepa.State.load(path)
    else:
        instances = [p.name for brief in best for p in load_personas(brief)]
        state = gepa.start(instances, seed_rules=load_locked_rules())
    state = gepa.optimize(state, gepa.make_runner(best, platform, runs), budget, path, minibatch=minibatch, runs_per_case=runs)
    top = gepa.top(state.pool)
    return {"iterations": state.iteration, "rollouts": state.rollouts, "pool": len(state.pool),
            "front": [c.id for c in gepa.pareto_front(state.pool)],
            "top": [{"id": c.id, "mean": c.mean, "origin": c.origin, "rules": c.rules} for c in top],
            "seed_mean": state.pool[0].mean, "state": str(path)}


def gepa_confirm(best: dict[str, AgentConfig], practice: str, platform: str, runs: int, k: int) -> dict:
    state = gepa.State.load(state_path())
    seed = state.pool[0]
    results = []
    for candidate in gepa.top(state.pool, k):
        if candidate.id == seed.id:
            continue
        summary = gate(best, with_rules(best, candidate.rules, f"gepa-{candidate.id}"), practice, platform, runs)
        results.append({"id": candidate.id, "local_gain": candidate.mean - seed.mean, "decision": summary["decision"],
                        "win": summary["win"], "practice": summary["practice"]["paired"], "rules": candidate.rules})
    winners = sorted((r for r in results if r["win"]), key=lambda r: -r["practice"]["mean_diff"])
    if winners:
        lock_rules(winners[0]["rules"], f"GEPA-lite {winners[0]['id']} confirmed on {platform}")
        outcome = f"merged {winners[0]['id']} into the template"
    elif results and all(r["local_gain"] > 0 for r in results):
        outcome = "drop GEPA: local scores rose but none of the top candidates wins on Freya (judge and Freya disagree)"
    else:
        outcome = "nothing confirmed; template unchanged"
    return {"candidates": results, "outcome": outcome}


# --- AFlow-lite -------------------------------------------------------------------------------------------------


def scored_runs(label: str, brief: str) -> list[ScoredRun]:
    return [s for f in sorted((RUNS_DIR / label).glob(f"{brief}_ab_B_vs_*.jsonl")) for s in load_jsonl(f, ScoredRun)]


def with_graph(best: dict[str, AgentConfig], graph: aflow.Graph) -> dict[str, AgentConfig]:
    out = {}
    for brief, cfg in best.items():
        variant = aflow.attach(cfg, graph)
        save_json(RUNS_DIR / variant.version_label / "agent.json", variant)
        out[brief] = variant
    return out


def aflow_run(best: dict[str, AgentConfig], practice: str, platform: str, runs: int) -> dict:
    trials = []
    for graph in aflow.shapes()[1:]:  # shape 0 is the single-prompt agent = current best
        variant = with_graph(best, graph)
        summary = gate(best, variant, practice, platform, runs)
        trials.append({"shape": graph.name, "win": summary["win"], "decision": summary["decision"],
                       "practice": summary["practice"]["paired"], "label": variant[practice].version_label, "graph": graph})
    winners = [t for t in trials if t["win"]]
    lead = max(winners or trials, key=lambda t: t["practice"]["mean_diff"])
    chosen = lead["graph"] if winners else None
    edited = aflow.edit(lead["graph"], failure_clusters(scored_runs(lead["label"], practice)))
    current = with_graph(best, chosen) if chosen else best
    edit_summary = gate(current, with_graph(best, edited), practice, platform, runs)
    if edit_summary["win"]:
        chosen = edited
    if chosen:
        lock_workflow(chosen.model_dump(), f"AFlow-lite on {practice}")
    return {"trials": [{k: v for k, v in t.items() if k != "graph"} for t in trials],
            "edit": {"from": lead["shape"], "graph": edited.model_dump(), "decision": edit_summary["decision"]},
            "chosen": chosen.name if chosen else "single (simple graph stays)"}


# --- lessons library --------------------------------------------------------------------------------------------


def lessons_test(best: dict[str, AgentConfig], practice: str, platform: str, runs: int) -> dict:
    proposed = [lesson["rule"] for lesson in json.loads(lessons.LESSONS_PATH.read_text()) if lesson["status"] == "proposed"]
    if not proposed:
        return {"outcome": "no proposed lessons"}
    summary = gate(best, with_rules(best, [*load_locked_rules(), *proposed], "lessons"), practice, platform, runs)
    if summary["accepted"]:  # "her durumda yapılır": kept unless it makes something worse
        lock_rules(proposed, f"lessons library, gate: {summary['decision']}")
        lessons.set_status(proposed, "locked")
    else:
        lessons.set_status(proposed, "rejected")
    return {"rules": proposed, "gate": summary, "outcome": "locked" if summary["accepted"] else "rejected"}


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    def common(p, needs_best=True):
        p.add_argument("--practice", required=True)
        p.add_argument("--fake", default="")
        p.add_argument("--platform", default="local")
        p.add_argument("--runs", type=int, default=3)
        if needs_best:
            p.add_argument("--best", required=True, help="agent path; {brief} is replaced per brief")

    g = sub.add_parser("gepa").add_subparsers(dest="action", required=True)
    g_run = g.add_parser("run")
    common(g_run)
    g_run.add_argument("--budget", type=int, default=3000, help="conversations")
    g_run.add_argument("--minibatch", type=int, default=6)
    g_run.add_argument("--resume", action="store_true")
    g_run.add_argument("--force", action="store_true")
    g_run.set_defaults(runs=1)
    g_confirm = g.add_parser("confirm")
    common(g_confirm)
    g_confirm.add_argument("--top", type=int, default=3)
    g_confirm.set_defaults(platform="freya")
    common(sub.add_parser("aflow"))
    lsn = sub.add_parser("lessons").add_subparsers(dest="action", required=True)
    l_mine = lsn.add_parser("mine")
    l_mine.add_argument("--runs", nargs="+", required=True, help="scored-run JSONL files from practice")
    l_mine.add_argument("--min-count", type=int, default=3)
    common(lsn.add_parser("test"))
    args = parser.parse_args(argv)

    if args.cmd == "lessons" and args.action == "mine":
        scored = [s for path in args.runs for s in load_jsonl(Path(path), ScoredRun)]
        result = {"lessons": lessons.mine(scored, load_locked_rules(), args.min_count)}
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return result

    fakes = [b for b in args.fake.split(",") if b] or [b for b in list_briefs() if b != args.practice]
    best = agents_for(args.best, [args.practice, *fakes])
    if args.practice not in best:
        raise SystemExit(f"no agent for the practice brief {args.practice}")
    if args.cmd == "gepa" and args.action == "run":
        result = gepa_run(best, args.practice, args.budget, args.platform, args.runs, args.minibatch, args.resume, args.force)
    elif args.cmd == "gepa":
        result = gepa_confirm(best, args.practice, args.platform, args.runs, args.top)
    elif args.cmd == "aflow":
        result = aflow_run(best, args.practice, args.platform, args.runs)
    else:
        result = lessons_test(best, args.practice, args.platform, args.runs)
    name = f"{args.cmd}_{getattr(args, 'action', '')}".rstrip("_")
    out = results_dir(args.practice, "section4") / f"{name}.json"
    dump(out, result)
    if isinstance(result.get("gate"), dict):
        report(result["gate"], out)
    print(json.dumps({k: v for k, v in result.items() if k not in ("gate", "trials")}, ensure_ascii=False, indent=1, default=str)[:3000])
    return result


if __name__ == "__main__":
    main()
