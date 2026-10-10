import json
import shutil
from pathlib import Path

import pytest

from builder.agentic import review
from tests.agentic.conftest import REPO

FIX = REPO / "tests" / "agentic" / "fixtures"
BRIEF = "1. Ask for the six-digit member code first.\n2. Offer a colleague when a life event stops payment.\n3. Never mention money before identity.\n"


def test_review_workspace_has_no_builder_interpretation(tmp_path):
    brief = tmp_path / "brief.md"
    brief.write_text(BRIEF)
    ws = tmp_path / "rws"
    review.build_review_workspace(ws, [brief], FIX / "pattern_demo.openapi.json", FIX / "pattern_demo.workflow.json")
    files = sorted(str(p.relative_to(ws)) for p in ws.rglob("*") if p.is_file())
    assert files == ["docs/api.md", "docs/tools-and-code.md", "docs/workflow-format.md", "input/brief-1.md",
                     "input/tools.openapi.json", "input/workflow.json"]
    assert not list(ws.rglob("rules.json")) and not list(ws.rglob("policy.json")) and not list(ws.rglob(".claude"))


def test_parse_review_is_lenient(tmp_path):
    assert "no usable review" in review.parse_review(tmp_path / "missing.json")["error"]
    (tmp_path / "r.json").write_text(json.dumps({"rules": [{"source_quote": "q", "verdict": "BROKEN"}, "junk",
                                                           {"id": "V2", "verdict": "Missing", "node_ids": ["a", None]}]}))
    rules = review.parse_review(tmp_path / "r.json")["rules"]
    assert [r["verdict"] for r in rules] == ["ok", "missing"] and rules[1]["node_ids"] == ["a"]


def test_compare_finds_unlisted_rules_and_defects():
    builder_rules = [{"source_quote": "Ask for the six-digit member code first"},
                     {"source_quote": "Never mention money before identity"}]
    rv = {"rules": [
        {"id": "V1", "source_quote": "ask for the SIX-DIGIT member code first.", "statement": "s", "verdict": "ok", "node_ids": [], "defect": "", "fix": ""},
        {"id": "V2", "source_quote": "Offer a colleague when a life event stops payment", "statement": "offer help", "verdict": "ok", "node_ids": [], "defect": "", "fix": ""},
        {"id": "V3", "source_quote": "Never mention money before identity", "statement": "s", "verdict": "wrong", "node_ids": ["opening"], "defect": "the opening names the item", "fix": "remove it"},
        {"id": "V4", "source_quote": "x", "statement": "too short to judge", "verdict": "ok", "node_ids": [], "defect": "", "fix": ""}]}
    findings = review.compare(rv, builder_rules)
    assert [(f["review_id"], f["kind"]) for f in findings] == [("V2", "unlisted_rule"), ("V3", "defect")]
    text = review.fix_prompt(findings, 5)
    assert "nodes: opening" in text and "not in your rules.json" in text and "mcp__fb__lint_workflow" in text


def test_build_review_and_fix_flow(tmp_path):
    pytest.importorskip("claude_agent_sdk")
    from claude_agent_sdk import ResultMessage

    from builder.agentic import run as run_mod

    seen = []

    async def query(prompt, options):
        cwd = Path(options.cwd)
        out = cwd / "out"
        if prompt.startswith("Review the phone agent"):
            seen.append(("review", cwd, sorted(p.name for p in cwd.rglob("*") if p.is_file())))
            (out / "review.json").write_text(json.dumps({"rules": [
                {"id": "V1", "source_quote": "Offer a colleague when a life event stops payment", "statement": "offer help",
                 "verdict": "missing", "node_ids": ["negotiate"], "defect": "no offer", "fix": "add a stage node"}]}))
        elif "independent reviewer" in prompt:
            seen.append(("fix", cwd, options.resume))
        else:
            seen.append(("build", cwd, None))
            shutil.copyfile(FIX / "pattern_demo.workflow.json", out / "workflow.json")
            (out / "rules.json").write_text(json.dumps([{"source_quote": "Ask for the six-digit member code first"}]))
            (out / "policy.json").write_text("{}")
        yield ResultMessage(subtype="success", duration_ms=10, duration_api_ms=5, is_error=False, num_turns=1,
                            session_id="sess-1", total_cost_usd=0.01)

    brief = tmp_path / "brief.md"
    brief.write_text(BRIEF)
    o = run_mod.BuildOptions(briefs=[brief], api=FIX / "pattern_demo.openapi.json", slot="agentic-test", out_dir=tmp_path / "out", save="none")
    report = run_mod.run(o, query_fn=query, validate_fn=lambda wf, n: {"skipped": "no key"}, trace_root=tmp_path / "traces")
    assert [s[0] for s in seen] == ["build", "review", "fix"]
    assert seen[1][1] != seen[0][1] and "rules.json" not in seen[1][2] and "policy.json" not in seen[1][2]
    assert seen[2][1] == seen[0][1] and seen[2][2] == "sess-1"  # the fix resumes the builder's own session
    assert report["review"]["findings"] == 1 and report["review"]["fix_ran"] and report["review"]["fix_resumed"]
    assert json.loads((tmp_path / "out" / "findings.json").read_text())[0]["kind"] == "unlisted_rule_and_defect"
    assert (tmp_path / "out" / "review.json").exists() and report["status"] == "ok"
    assert "review" in (Path(report["trace"]) / "trace.txt").read_text()


def test_review_off_runs_one_phase(tmp_path):
    pytest.importorskip("claude_agent_sdk")
    from builder.agentic import run as run_mod

    calls = []

    async def query(prompt, options):
        calls.append(prompt[:20])
        shutil.copyfile(FIX / "pattern_demo.workflow.json", Path(options.cwd) / "out" / "workflow.json")
        return
        yield

    brief = tmp_path / "brief.md"
    brief.write_text(BRIEF)
    o = run_mod.BuildOptions(briefs=[brief], api=FIX / "pattern_demo.openapi.json", slot="agentic-test", out_dir=tmp_path / "out",
                             save="none", review=False)
    report = run_mod.run(o, query_fn=query, validate_fn=lambda wf, n: {"skipped": "no key"}, trace_root=tmp_path / "traces")
    assert len(calls) == 1 and report["review"] == {"ran": False} and report["status"] == "ok"


def test_fix_prompt_puts_model_limit_defects_first():
    fs = [{"kind": "unlisted_rule", "review_id": "V1", "rule": "r1", "quote": "q1", "node_ids": [], "defect": "", "fix": ""},
          {"kind": "defect", "review_id": "V2", "rule": "r2", "quote": "q2", "node_ids": ["a"], "defect": "wrong queue", "fix": "use x"},
          {"kind": "defect", "review_id": "V3", "rule": "r3", "quote": "q3", "node_ids": ["b"], "defect": "attempts are left to the model", "fix": "count in code"}]
    text = review.fix_prompt(fs, 7)
    assert text.index("r3") < text.index("r2") < text.index("r1") and "in the order given" in text
