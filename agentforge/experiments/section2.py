"""TEST_PLAN section 2: the behaviour bundle (P1), then the one-at-a-time tests.

Agent paths take `{brief}`: every brief has its own V1 (`runs/col-{brief}-v1/agent.json` from the builder), and a
variant is that V1 plus add-ons rendered with the brief's own tool names and limits.

python -m agentforge.experiments.section2 cluster --brief practice --agent runs/col-practice-v1/agent.json
    Most frequent failed checks in the baseline runs -> which P1 items address them (the plan: top 5-8 failure types
    decide the bundle).
python -m agentforge.experiments.section2 p1 --best 'runs/col-{brief}-v1/agent.json' --practice practice [--items auto]
    P1 vs current best through the gate. Win -> lock, then try dropping any item that grows the prompt > 30%.
    Equal -> split in two, find the harmful half, gate the other half. Loss -> bisect to the item that breaks
    something, drop it, gate the rest.
python -m agentforge.experiments.section2 single --test T2.2|T2.3|T2.4 --best ... --practice practice
python -m agentforge.experiments.section2 rebuild --test T2.5|T2.6 --practice practice
    T2.5 / T2.6 change the builder itself, so both arms are built fresh for every brief.
"""

from __future__ import annotations

import argparse
import collections
from pathlib import Path
from typing import Callable

from agentforge.build.addons import ADDONS, P1, SINGLE_TESTS, apply_addons, growth, lock, lock_builder_option, render
from agentforge.config import RUNS_DIR
from agentforge.domain.collections import brief_dir, list_briefs, load_policy
from agentforge.domain.collections.cases import case_of
from agentforge.experiments.col_common import dump, load_agent, results_dir
from agentforge.experiments.paired import agents_for, compare_brief, gate, report
from agentforge.schemas import AgentConfig, ScoredRun
from agentforge.stats import ALPHA
from agentforge.store import load_jsonl, save_json

GROWTH_LIMIT = 0.30
TOP_FAILURES = 8
SINGLE_GROUPS = {"T2.2": ("promise",), "T2.3": ("promise",), "T2.4": None}


# --- failure clusters -------------------------------------------------------------------------------------------


def failure_clusters(scored: list[ScoredRun]) -> dict:
    """Failed checks are the clusters: every decision check has a name, so no LLM is needed to group them."""
    by_check = collections.Counter()
    by_case: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for item in scored:
        case = case_of(item.run.persona_name)
        for v in item.verdicts:
            if not v.passed and not v.reason.startswith("ERROR"):
                by_check[v.check_name] += 1
                by_case[v.check_name][case.key if case else item.run.persona_name] += 1
    return {"runs": len(scored), "top": [{"check": c, "fails": n, "cases": dict(by_case[c].most_common())}
                                         for c, n in by_check.most_common()]}


def choose_items(clusters: dict, top: int = TOP_FAILURES) -> list[str]:
    """P1 items aimed at one of the most frequent failure types. Generic items ('success' only) never decide alone."""
    frequent = {row["check"] for row in clusters["top"][:top]}
    chosen = [k for k in P1 if frequent & set(ADDONS[k].checks)]
    return chosen or list(P1)


def baseline_runs(agent: AgentConfig, brief: str) -> list[ScoredRun]:
    return [s for f in sorted((RUNS_DIR / agent.version_label).glob(f"{brief}_baseline_*.jsonl")) for s in load_jsonl(f, ScoredRun)]


# --- variants ---------------------------------------------------------------------------------------------------


def variants(best: dict[str, AgentConfig], keys: list[str], suffix: str) -> dict[str, AgentConfig]:
    """best + add-ons for every brief, saved so the runs can be inspected and re-used."""
    out = {}
    for brief, cfg in best.items():
        variant = apply_addons(cfg, load_policy(brief_dir(brief)), keys, label=f"{cfg.version_label}+{suffix}")
        save_json(RUNS_DIR / variant.version_label / "agent.json", variant)
        out[brief] = variant
    return out


def halves(items: list[str]) -> tuple[list[str], list[str]]:
    mid = (len(items) + 1) // 2
    return items[:mid], items[mid:]


Evaluate = Callable[[list[str]], dict]  # add-on keys -> practice comparison of best+keys vs best


def harmful_half(items: list[str], evaluate: Evaluate) -> tuple[list[str], list[str], list[dict]]:
    """Split once; the half whose comparison against best is worse is the harmful one. Returns (harmful, other, trace)."""
    left, right = halves(items)
    if not right:
        return left, [], []
    a, b = evaluate(left), evaluate(right)
    trace = [{"items": left, **_brief_view(a)}, {"items": right, **_brief_view(b)}]
    worse_left = (a["verdict"] == "loss", -a["paired"]["mean_diff"]) >= (b["verdict"] == "loss", -b["paired"]["mean_diff"])
    return (left, right, trace) if worse_left else (right, left, trace)


def find_culprit(items: list[str], evaluate: Evaluate, max_steps: int = 6) -> tuple[list[str], list[dict]]:
    """Binary search for the item that breaks something: keep the worse half until one item (or the budget) is left."""
    trace: list[dict] = []
    while len(items) > 1 and len(trace) + 2 <= max_steps:
        items, _, step = harmful_half(items, evaluate)
        trace += step
    return items, trace


def _brief_view(result: dict) -> dict:
    return {"verdict": result["verdict"], "mean_diff": result["paired"]["mean_diff"], "p": result["paired"]["p"]}


# --- commands ---------------------------------------------------------------------------------------------------


def run_p1(best: dict[str, AgentConfig], practice: str, items: list[str], platform: str, runs: int, max_steps: int) -> dict:
    def evaluate(keys: list[str]) -> dict:
        return compare_brief(best[practice], variants({practice: best[practice]}, keys, "-".join(keys))[practice],
                             practice, platform, runs, "p1_split")

    log: dict = {"items": items}
    summary = gate(best, variants(best, items, "p1"), practice, platform, runs)
    log["p1"] = summary
    verdict = summary["practice"]["verdict"]
    final = items if summary["win"] else None

    if summary["win"]:
        long_items = [k for k in items if growth(best[practice], load_policy(brief_dir(practice)), k) > GROWTH_LIMIT]
        log["long_items"] = long_items
        for key in long_items:  # simpler wins: drop the item if the bundle without it is not worse
            without = [k for k in final if k != key]
            check = compare_brief(variants({practice: best[practice]}, final, "p1")[practice],
                                  variants({practice: best[practice]}, without, f"p1-minus-{key}")[practice],
                                  practice, platform, runs, f"drop_{key}")
            log.setdefault("drop_tests", []).append({"item": key, **_brief_view(check)})
            if check["verdict"] != "loss":
                final = without
    elif verdict == "equal" or verdict == "loss":
        if verdict == "equal":
            harmful, rest, trace = harmful_half(items, evaluate)
        else:
            harmful, trace = find_culprit(items, evaluate, max_steps)
            rest = [k for k in items if k not in harmful]
        log.update({"search": trace, "harmful": harmful, "next": rest})
        if rest:
            retry = gate(best, variants(best, rest, "p1-" + "-".join(rest) if len(rest) <= 2 else f"p1-{len(rest)}"), practice,
                         platform, runs)
            log["next_gate"] = retry
            final = rest if retry["win"] else None

    if final:
        lock(final, f"section 2 P1 on {practice}: {summary['decision']}")
    log["locked"] = final or []
    return log


def run_single(test: str, best: dict[str, AgentConfig], practice: str, platform: str, runs: int) -> dict:
    a_key, b_key = SINGLE_TESTS[test]
    arm_a = variants(best, [a_key], a_key) if a_key and b_key else best
    arm_b = variants(best, [b_key or a_key], b_key or a_key)
    summary = gate(arm_a, arm_b, practice, platform, runs, SINGLE_GROUPS[test])
    p = summary["practice"]["paired"]
    if summary["win"]:
        winner = b_key or a_key
        lock([winner], f"{test} on {practice}: B ahead")
    elif b_key and summary["practice"]["verdict"] == "loss" and p["mean_diff"] < 0 and p["p"] < ALPHA and not summary["practice"]["veto"]:
        winner = None  # A looked better, but the gate only confirms B; swap the arms to confirm A before locking it
        summary["note"] = f"{a_key} ahead on practice; re-run with arms swapped to confirm and lock it"
    else:
        winner = None  # equal: nothing locked; for T2.4 that means no examples (shorter prompt)
    return {"test": test, "arms": [a_key, b_key or a_key], "gate": summary, "locked": winner}


REBUILD_TESTS = {"T2.5": ("prompt_language", "tr", "en"), "T2.6": ("reading", "conservative", "liberal")}

# --- dry run: no model calls ----------------------------------------------------------------------------------

MINUTES_PER_CONVERSATION = 0.1  # measured on the local platform: ~3 minutes per 30 calls at SIM_CONCURRENCY=12


def _cases(brief: str, label: str | None, groups: tuple[str, ...] | None) -> tuple[int, int]:
    """(cases a comparison runs on this brief, critical regression cases) from the baseline if there is one."""
    import json

    from agentforge.domain.collections import load_personas

    names = {p.name: case_of(p.name).group for p in load_personas(brief) if case_of(p.name)}
    dev, regression = list(names), []
    path = results_dir(brief, label) / "baseline.json" if label else None
    if path and path.exists():
        data = json.loads(path.read_text())
        dev, regression = data["dev_set"], data["critical_regression_set"]
    return len([c for c in dev if not groups or names.get(c) in groups]), len(regression)


def _gate_cost(briefs: list[str], practice: str, labels: dict[str, str | None], runs: int,
               groups: tuple[str, ...] | None) -> tuple[int, int]:
    """(conversations if the practice result is not a win, conversations if it is: re-run + regression on top)."""
    per = {b: 2 * _cases(b, labels.get(b), groups)[0] * runs for b in briefs}
    base = sum(per.values())
    extra = per.get(practice, 0) + _cases(practice, labels.get(practice), groups)[1] * runs if practice in per else 0
    return base, base + extra


def plan(practice: str, briefs: list[str], best: dict[str, AgentConfig], runs: int, max_steps: int) -> dict:
    labels = {b: best[b].version_label if b in best else None for b in briefs}
    review: dict[str, dict] = {}
    for brief in briefs:
        policy = load_policy(brief_dir(brief))
        review[brief] = {key: {"test": addon.test, "skip": addon.skip(policy), "chars": len(addon.text(policy)),
                               "growth": growth(best[brief], policy, key) if brief in best else None}
                         for key, addon in ADDONS.items()}

    def differs(brief: str, a: list[str], b: list[str]) -> bool:
        policy = load_policy(brief_dir(brief))
        return render(policy, a) != render(policy, b)

    tests = {}
    arms = {"P1": ([], list(P1), None), **{t: ([k for k in [a] if b], [b or a], SINGLE_GROUPS[t]) for t, (a, b) in SINGLE_TESTS.items()}}
    for test, (arm_a, arm_b, groups) in arms.items():
        tested = [b for b in briefs if differs(b, arm_a, arm_b)]
        skipped = {b: sorted({ADDONS[k].skip(load_policy(brief_dir(b))) for k in arm_a + arm_b} - {None}) for b in briefs if b not in tested}
        low, high = _gate_cost(tested, practice, labels, runs, groups)
        if test == "P1":  # a tie or loss adds the split search (practice only) and one more gate
            search = max_steps * _gate_cost([practice], practice, labels, runs, None)[0] // 2
            high = max(high, low + search + low)
        fakes = [b for b in tested if b != practice]
        tests[test] = {"briefs_tested": tested, "skipped": skipped, "conversations": [low, high],
                       "minutes": [round(low * MINUTES_PER_CONVERSATION), round(high * MINUTES_PER_CONVERSATION)],
                       "decidable": practice in tested and len(fakes) >= 3,
                       "why_not": None if practice in tested and len(fakes) >= 3 else
                                  "practice brief fixes this" if practice not in tested else f"only {len(fakes)} fake briefs differ (need 3)"}
    for test in REBUILD_TESTS:
        low, high = _gate_cost(briefs, practice, labels, runs, None)
        tests[test] = {"briefs_tested": briefs, "builder_calls": 2 * len(briefs), "conversations": [low, high],
                       "minutes": [round(low * MINUTES_PER_CONVERSATION), round(high * MINUTES_PER_CONVERSATION)],
                       "decidable": len(briefs) - 1 >= 3}
    return {"practice": practice, "runs": runs, "addons": review, "tests": tests,
            "total_minutes": [sum(t["minutes"][0] for t in tests.values()), sum(t["minutes"][1] for t in tests.values())],
            "rendered": {b: render(load_policy(brief_dir(b)), list(ADDONS)) for b in briefs}}


def plan_markdown(result: dict) -> str:
    lines = [f"# Section 2 dry run (practice: {result['practice']}, {result['runs']} runs per case)", "",
             "No model calls. Conversation counts assume the baseline case sets when a baseline exists, else all 16 cases;",
             f"minutes use {MINUTES_PER_CONVERSATION} min per conversation (local platform, measured).", "",
             "| Test | Briefs run | Decidable | Conversations | Minutes |", "|---|---|---|---|---|"]
    for test, t in result["tests"].items():
        decidable = "yes" if t["decidable"] else f"no: {t.get('why_not') or 'fewer than 3 fake briefs'}"
        lines.append(f"| {test} | {len(t['briefs_tested'])} | {decidable} | {t['conversations'][0]}–{t['conversations'][1]} | "
                     f"{t['minutes'][0]}–{t['minutes'][1]} |")
    lines += ["", f"All of section 2: {result['total_minutes'][0]}–{result['total_minutes'][1]} minutes "
              "(the plan budgets ~4 hours).", "", "## Add-ons skipped per brief", ""]
    for brief, addons in result["addons"].items():
        skipped = [f"`{k}`: {a['skip']}" for k, a in addons.items() if a["skip"]]
        lines.append(f"- **{brief}**: " + ("; ".join(skipped) if skipped else "none"))
    lines += ["", "## Rendered add-ons per brief (review before running)", ""]
    for brief, text in result["rendered"].items():
        lines += [f"### {brief}", "", text, ""]
    return "\n".join(lines) + "\n"


def run_rebuild(test: str, practice: str, briefs: list[str], platform: str, runs: int) -> dict:
    from agentforge.build.builder import build_agent
    from agentforge.domain import load_domain
    from agentforge.domain.collections import load_personas

    option, a_value, b_value = REBUILD_TESTS[test]
    arms: dict[str, dict[str, AgentConfig]] = {a_value: {}, b_value: {}}
    for brief in briefs:
        task_md, tools = load_domain(brief_dir(brief))
        variables = sorted(load_personas(brief)[0].variables)
        for value in (a_value, b_value):
            try:
                cfg = build_agent(task_md, tools, variables=variables, label=f"col-{brief}-{test}-{value}", **{option: value})
            except Exception as error:  # section 5 item 4: a builder error on any brief counts against that arm
                print(f"builder failed for {brief} ({option}={value}): {error}")
                continue
            save_json(RUNS_DIR / cfg.version_label / "agent.json", cfg)
            arms[value][brief] = cfg
    summary = gate(arms[a_value], arms[b_value], practice, platform, runs)
    locked = None
    if summary["win"]:
        locked = lock_builder_option(option, b_value, f"{test} on {practice}")
    return {"test": test, "option": option, "arms": [a_value, b_value], "gate": summary, "locked": locked,
            "build_failures": {v: sorted(set(briefs) - set(arms[v])) for v in arms}}


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_cluster = sub.add_parser("cluster")
    p_cluster.add_argument("--brief", required=True)
    p_cluster.add_argument("--agent", required=True)
    for name in ("p1", "single", "rebuild", "plan"):
        p = sub.add_parser(name)
        p.add_argument("--practice", required=True)
        p.add_argument("--fake", default="")
        p.add_argument("--platform", default="local")
        p.add_argument("--runs", type=int, default=3)
        if name not in ("rebuild", "plan"):
            p.add_argument("--best", required=True, help="agent path; {brief} is replaced per brief")
        if name == "plan":
            p.add_argument("--best", default="", help="optional agent path with {brief}, for prompt growth and baselines")
            p.add_argument("--max-steps", type=int, default=6)
        elif name == "p1":
            p.add_argument("--items", default="auto", help="auto (from baseline failures) | all | comma-separated keys")
            p.add_argument("--max-steps", type=int, default=6)
        else:
            p.add_argument("--test", required=True, choices=sorted(SINGLE_TESTS if name == "single" else REBUILD_TESTS))
    args = parser.parse_args(argv)

    if args.cmd == "cluster":
        agent = load_agent(args.agent)
        clusters = failure_clusters(baseline_runs(agent, args.brief))
        clusters["p1_items"] = choose_items(clusters)
        dump(results_dir(args.brief, agent.version_label) / "clusters.json", clusters)
        for row in clusters["top"][:TOP_FAILURES]:
            print(f"{row['fails']:4d}  {row['check']}  {row['cases']}")
        print(f"P1 items: {', '.join(clusters['p1_items'])}")
        return clusters

    fakes = [b for b in args.fake.split(",") if b] or [b for b in list_briefs() if b != args.practice]
    briefs = [args.practice, *fakes]
    if args.cmd == "plan":
        best = agents_for(args.best, briefs) if args.best else {}
        result = plan(args.practice, briefs, best, args.runs, args.max_steps)
        out = results_dir(args.practice, "section2") / "plan.md"
        out.write_text(plan_markdown(result))
        dump(out.with_suffix(".json"), result)
        print(plan_markdown(result).split("## Rendered")[0] + f"full review: {out}")
        return result
    if args.cmd == "rebuild":
        result = run_rebuild(args.test, args.practice, briefs, args.platform, args.runs)
    else:
        best = agents_for(args.best, briefs)
        if args.practice not in best:
            raise SystemExit(f"no agent for the practice brief {args.practice}")
        if args.cmd == "single":
            result = run_single(args.test, best, args.practice, args.platform, args.runs)
        else:
            if args.items == "auto":
                clusters = failure_clusters(baseline_runs(best[args.practice], args.practice))
                items = choose_items(clusters) if clusters["runs"] else list(P1)
            else:
                items = list(P1) if args.items == "all" else [k for k in args.items.split(",") if k]
            unknown = [k for k in items if k not in ADDONS]
            if unknown:
                raise SystemExit(f"unknown add-ons: {unknown}; known: {', '.join(ADDONS)}")
            result = run_p1(best, args.practice, items, args.platform, args.runs, args.max_steps)
    out = results_dir(args.practice, "section2") / f"{args.cmd}{'_' + args.test if args.cmd != 'p1' else ''}.json"
    dump(out, result)
    main_gate = result.get("gate") or result.get("p1")
    if main_gate:
        report(main_gate, out)
    print(f"locked: {result.get('locked')}")
    return result


if __name__ == "__main__":
    main()
