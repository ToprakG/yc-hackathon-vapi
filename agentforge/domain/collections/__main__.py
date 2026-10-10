"""Collections brief packs.

python -m agentforge.domain.collections prepare [--brief ID]     regenerate tools/accounts/personas/unit tests/checks
python -m agentforge.domain.collections new ID --from brief.md   kickoff: copy a real brief in, extract its policy (LLM), prepare
python -m agentforge.domain.collections check                    offline sanity check of every brief folder
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from agentforge.domain import load_domain
from agentforge.domain.collections import BRIEFS_DIR, brief_dir, list_briefs, load_accounts, make_accounts, tools_for
from agentforge.domain.collections.cases import CASES, personas_for
from agentforge.domain.collections.policy import CANONICAL_TOOLS, extract_policy, load_policy
from agentforge.domain.collections.unit_tests import unit_tests_for
from agentforge.store import load_models, save_json
from agentforge.schemas import Persona, UnitTest


def prepare(brief: str) -> None:
    path = brief_dir(brief)
    policy = load_policy(path)
    save_json(path / "tools.json", [t.model_dump(mode="json", exclude_defaults=True) for t in tools_for(policy)])
    if not (path / "accounts.json").exists():
        save_json(path / "accounts.json", make_accounts(policy))
    accounts = load_accounts(path)
    save_json(path / "personas.json", [p.model_dump(mode="json") for p in personas_for(policy, accounts)])
    save_json(path / "unit_tests.json", [u.model_dump(mode="json") for u in unit_tests_for(policy, accounts)])
    from agentforge.run.decision import describe

    save_json(path / "checks.json", describe(policy))
    print(f"{brief}: {len(CASES)} personas, 4 unit tests, {len(describe(policy))} checks")


def check(brief: str) -> list[str]:
    path = brief_dir(brief)
    problems = []
    policy = load_policy(path)
    _, tools = load_domain(path)
    names = {t.name for t in tools}
    missing = [policy.tool(c) for c in CANONICAL_TOOLS if policy.tool(c) not in names]
    if missing:
        problems.append(f"tools.json lacks {missing}")
    sop = (path / "sop.md").read_text()
    if policy.tool_names and not all(name in sop for name in policy.tool_names.values()):
        problems.append("renamed tools not all mentioned in sop.md")
    personas = load_models(path / "personas.json", Persona)
    if len(personas) != len(CASES) or any(not p.variables for p in personas):
        problems.append("personas.json stale; run prepare")
    tests = load_models(path / "unit_tests.json", UnitTest)
    if any(a.tool not in names for t in tests for a in t.tool_assertions):
        problems.append("unit test asserts on a tool the brief does not have")
    return problems


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_prepare = sub.add_parser("prepare")
    p_prepare.add_argument("--brief")
    p_new = sub.add_parser("new")
    p_new.add_argument("brief_id")
    p_new.add_argument("--from", dest="source", required=True)
    p_new.add_argument("--tools", default="", help="comma-separated tool names as the brief calls them")
    sub.add_parser("check")
    args = parser.parse_args(argv)

    if args.cmd == "new":
        path = BRIEFS_DIR / args.brief_id
        path.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(args.source), path / "sop.md")
        policy = extract_policy((path / "sop.md").read_text(), args.brief_id, [t for t in args.tools.split(",") if t])
        save_json(path / "policy.json", policy.model_dump(mode="json"))
        print(f"wrote {path / 'policy.json'}; review it against the brief before trusting any test built on it")
        prepare(args.brief_id)
    elif args.cmd == "prepare":
        for brief in [args.brief] if args.brief else list_briefs():
            prepare(brief)
    else:
        bad = {b: problems for b in list_briefs() if (problems := check(b))}
        for brief in list_briefs():
            print(f"{brief}: {'; '.join(bad[brief]) if brief in bad else 'ok'}")
        if bad:
            sys.exit(1)


if __name__ == "__main__":
    main()
