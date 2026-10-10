"""One agentic build: isolated workspace -> Claude Agent SDK run with our skill and tools -> deterministic finalize.

The agent sees only a temp directory holding the renamed briefs, the tool API, the kit docs, the invented
pattern_demo example and the skill. Finalize (not the agent) picks the lint-clean workflow, strips agent_config,
validates, saves to Freya when asked, exports, writes build_report.json and closes the trace.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from builder.agentic import guard, mcp_server, prompt, review
from builder.agentic.tools import lint, openapi_summary, validate
from builder.agentic.tools.clock import Clock
from builder.common.io import REPO, SKILL_NAME, build_workspace
from builder.common.trace import Trace

FILE_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep"]
DENIED_TOOLS = ["Bash", "BashOutput", "KillShell", "WebFetch", "WebSearch", "Task", "Agent", "NotebookEdit"]
STATE_FILE = REPO / ".freya-agents.json"  # absolute: the same slot always updates the same workflow


@dataclass
class BuildOptions:
    briefs: list
    api: Path
    slot: str
    out_dir: Path
    save: str = "freya"
    max_minutes: float = 18.0
    review: bool = True
    review_minutes: float = 5.0
    fix_minutes: float = 5.0
    model: str = "claude-opus-5-5"
    max_usd: float | None = None
    keep_workspace: bool = False
    self_test: str = "none"
    max_turns: int = 200
    extra: dict = field(default_factory=dict)


def review_options(ws: Path, model: str, hook, max_turns: int = 80):
    """The reviewer: file tools only, no skills, no MCP, no project settings; Write is confined to out/ by the guard."""
    from claude_agent_sdk import ClaudeAgentOptions, HookMatcher  # noqa: PLC0415

    tools = ["Read", "Write", "Glob", "Grep"]
    return ClaudeAgentOptions(
        cwd=str(ws), model=model, tools=tools, allowed_tools=tools, disallowed_tools=DENIED_TOOLS + ["Edit", "Skill"],
        setting_sources=[], permission_mode="dontAsk", max_turns=max_turns, strict_mcp_config=True,
        env={"CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1"},
        hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[hook])]},
        system_prompt={"type": "preset", "preset": "claude_code", "append": review.ROLE},
    )


def sdk_options(ws: Path, model: str, hook, server, max_turns: int = 200, max_usd: float | None = None,
                resume: str | None = None):
    from claude_agent_sdk import ClaudeAgentOptions, HookMatcher  # noqa: PLC0415

    return ClaudeAgentOptions(
        resume=resume,
        cwd=str(ws),
        model=model,
        tools=FILE_TOOLS + ["Skill"],  # the base set: no Bash, no web, no subagents (types.py:1974)
        allowed_tools=FILE_TOOLS + mcp_server.tool_names(),
        disallowed_tools=DENIED_TOOLS,
        skills=[SKILL_NAME],
        setting_sources=["project"],  # the workspace's .claude/ only
        permission_mode="dontAsk",  # anything not pre-approved is refused
        max_turns=max_turns,
        max_budget_usd=max_usd,
        env={"CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1"},
        hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[hook])]},
        mcp_servers={mcp_server.SERVER: server},
        strict_mcp_config=True,
        system_prompt={"type": "preset", "preset": "claude_code", "append": prompt.ROLE},
    )


def reap_children(grace_s: float = 3.0) -> int:
    """Backstop after a timeout: SIGTERM, then SIGKILL, any CLI child the SDK still tracks (SDK_NOTES.md)."""
    try:
        from claude_agent_sdk._internal.transport import subprocess_cli as sc  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return 0
    pids = [getattr(p, "pid", None) for p in list(getattr(sc, "_ACTIVE_CHILDREN", set()) or [])]
    return kill_pids([p for p in pids if p], grace_s)


def kill_pids(pids, grace_s: float = 3.0) -> int:
    alive = []
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
            alive.append(pid)
        except (ProcessLookupError, PermissionError):
            pass
    deadline = time.monotonic() + grace_s
    while alive and time.monotonic() < deadline:
        for pid in list(alive):
            try:
                done, _ = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                done = pid
            if done:
                alive.remove(pid)
        time.sleep(0.1)
    for pid in alive:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return len(pids)


async def _agent_phase(query_fn, task: str, options, trace: Trace, seconds: float, state: dict):
    import anyio  # noqa: PLC0415  (an SDK dependency; its cancel scope lets the SDK's shielded close() run)

    async def consume():
        async for msg in query_fn(prompt=task, options=options):
            trace.message(msg)
            state["messages"] += 1
            if type(msg).__name__ == "ResultMessage":
                state["result"] = msg

    try:
        with anyio.fail_after(seconds):
            await consume()
    except TimeoutError:
        state["timed_out"] = True
        trace.event("timeout", f"{state.get('phase', 'agent')} stopped after {seconds / 60:g} minutes")
    except Exception as e:  # noqa: BLE001  (finalize runs whatever happened)
        state["error"] = repr(e)
        trace.event("error", repr(e))


def _result_summary(result) -> dict:
    if result is None:
        return {}
    return {"subtype": result.subtype, "turns": result.num_turns, "duration_s": round(result.duration_ms / 1000),
            "cost_usd": result.total_cost_usd, "usage": result.usage, "terminal_reason": getattr(result, "terminal_reason", None),
            "is_error": result.is_error}


def _phase(query_fn, task, options, trace, minutes, name) -> dict:
    state = {"phase": name, "messages": 0, "result": None, "timed_out": False, "error": None}
    trace.event("phase", f"{name} starts ({minutes:g} min)")
    asyncio.run(_agent_phase(query_fn, task, options, trace, minutes * 60, state))
    if state["timed_out"]:
        trace.event("timeout", f"reaped {reap_children()} CLI process(es)")
    return state


def _reviewable(ws: Path) -> Path | None:
    """The workflow to review: the agent's file if it lints clean, else last_good."""
    out = ws / "out"
    api = openapi_summary.load(ws / "input" / "tools.openapi.json")
    if not lint.lint_file(out / "workflow.json", api, out / "policy.json")["errors"]:
        return out / "workflow.json"
    return out / "last_good.workflow.json" if (out / "last_good.workflow.json").exists() else None


def review_and_fix(ws: Path, opts: BuildOptions, trace: Trace, query_fn, main_state: dict, bound, workspace_root=None) -> dict:
    """One fresh-context review, code comparison with rules.json, and at most one fix round."""
    info = {"ran": False, "findings": 0, "fix_ran": False}
    target = _reviewable(ws)
    if target is None:
        info["skipped"] = "no lint-clean workflow to review"
        return info
    rws = Path(tempfile.mkdtemp(prefix="fb-review-", dir=workspace_root))
    parsed = {"rules": [], "error": "review did not run"}
    try:
        review.build_review_workspace(rws, opts.briefs, opts.api, target)
        task = review.review_prompt(len(opts.briefs), opts.review_minutes)
        state = _phase(query_fn, task, review_options(rws, opts.model, guard.make_hook(rws, on_event=trace.event)),
                       trace, opts.review_minutes, "review")
        info.update(ran=True, agent=_result_summary(state["result"]), timed_out=state["timed_out"], error=state["error"])
        parsed = review.parse_review(rws / "out" / "review.json")
        if (rws / "out" / "review.json").exists():
            shutil.copyfile(rws / "out" / "review.json", ws / "out" / "review.json")
    finally:
        shutil.rmtree(rws, ignore_errors=True)
    try:
        rules = json.loads((ws / "out" / "rules.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        rules = []
    findings = review.compare(parsed, rules)
    (ws / "out" / "findings.json").write_text(json.dumps(findings, indent=1, ensure_ascii=False))
    info.update(review_rules=len(parsed["rules"]), findings=len(findings), parse_error=parsed.get("error"),
                kinds={k: sum(f["kind"] == k for f in findings) for k in {f["kind"] for f in findings}})
    trace.event("review", {k: info[k] for k in ("review_rules", "findings", "kinds")})
    if not findings or opts.fix_minutes <= 0:
        return info
    session = getattr(main_state.get("result"), "session_id", None)
    bound.clock = Clock(opts.fix_minutes)
    task = review.fix_prompt(findings, opts.fix_minutes)
    if not session:
        task = prompt.task_prompt(len(opts.briefs), opts.fix_minutes) + "\n\nThe files in out/ exist already. " + task
    options = sdk_options(ws, opts.model, guard.make_hook(ws, on_event=trace.event), mcp_server.build_server(bound),
                          opts.max_turns, opts.max_usd, resume=session)
    state = _phase(query_fn, task, options, trace, opts.fix_minutes, "fix")
    info.update(fix_ran=True, fix=_result_summary(state["result"]), fix_timed_out=state["timed_out"], fix_resumed=bool(session))
    return info


def _import_freya():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    import freya  # noqa: PLC0415

    return freya


def finalize(ws: Path, opts: BuildOptions, trace: Trace, freya_mod=None, validate_fn=validate.validate) -> dict:
    out, dest = ws / "out", Path(opts.out_dir)
    dest.mkdir(parents=True, exist_ok=True)
    api = openapi_summary.load(ws / "input" / "tools.openapi.json")
    report = {"status": "failed", "slot": opts.slot, "fallback_used": False, "saved": None, "validate": None}
    for name in ("policy.json", "rules.json", "review.json", "findings.json"):
        if (out / name).exists():
            shutil.copyfile(out / name, dest / name)
    chosen = None
    main_lint = lint.lint_file(out / "workflow.json", api, out / "policy.json")
    report["lint_agent_output"] = {"errors": len(main_lint["errors"]), "warnings": len(main_lint["warnings"])}
    if not main_lint["errors"]:
        chosen, final_lint = out / "workflow.json", main_lint
    elif (out / "last_good.workflow.json").exists():
        final_lint = lint.lint_file(out / "last_good.workflow.json", api, out / "policy.json")
        if not final_lint["errors"]:
            chosen, report["fallback_used"] = out / "last_good.workflow.json", True
    if (out / "workflow.json").exists() and chosen != out / "workflow.json":
        shutil.copyfile(out / "workflow.json", dest / "workflow.rejected.json")
    trace.event("finalize", {"chosen": chosen.name if chosen else None, "fallback": report["fallback_used"],
                             "agent_output_lint": report["lint_agent_output"]})
    if chosen is None:
        report["message"] = "no lint-clean workflow: neither out/workflow.json nor out/last_good.workflow.json passes lint"
        report["lint"] = {"errors": main_lint["errors"][:30]}
        return report
    wf = json.loads(chosen.read_text(encoding="utf-8"))
    if wf.pop("agent_config", None) is not None:
        trace.event("finalize", "stripped agent_config")
    report["lint"] = {"errors": 0, "warnings": len(final_lint["warnings"]), "warning_list": final_lint["warnings"][:40]}
    (dest / "workflow.json").write_text(json.dumps(wf, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    report["validate"] = validate_fn(wf, opts.slot)
    trace.event("check", {"validate (finalize)": report["validate"]})
    if opts.save == "freya":
        try:
            freya = freya_mod or _import_freya()
            saved = freya.save_workflow(opts.slot, wf, state_file=str(STATE_FILE))
            report["saved"] = saved
            trace.event("freya", {"saved": saved, "state_file": str(STATE_FILE)})
            exported = freya.export_workflow(saved["workflow_id"], str(dest / f"{opts.slot}.workflow.json"))
            report["exported"] = str(exported)
            trace.event("freya", {"exported": str(exported)})
        except Exception as e:  # noqa: BLE001
            report["message"] = f"save to Freya failed: {e}"
            trace.event("error", report["message"])
            return report
    else:
        trace.event("freya", "nothing created or updated (--save none)")
    report["status"] = "ok"
    return report


def run(opts: BuildOptions, query_fn=None, freya_mod=None, validate_fn=validate.validate, trace_root: Path | None = None,
        workspace_root: str | None = None) -> dict:
    t0 = time.monotonic()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    trace_name = opts.slot if opts.slot.startswith("agentic-") else f"agentic-{opts.slot}"
    trace = Trace(Path(trace_root or REPO / "traces") / f"{trace_name}-{stamp}", {
        "variant": "agentic", "slot": opts.slot, "model": opts.model, "briefs": [str(b) for b in opts.briefs],
        "tool_api": str(opts.api), "save": opts.save, "max_minutes": opts.max_minutes, "self_test": opts.self_test})
    ws = Path(tempfile.mkdtemp(prefix="fb-build-", dir=workspace_root))
    report: dict = {}
    try:
        build_workspace(ws, opts.briefs, opts.api)
        trace.event("workspace", {"path": str(ws), "files": sorted(str(p.relative_to(ws)) for p in ws.rglob("*") if p.is_file())[:60]})
        clock = Clock(opts.max_minutes)
        bound = mcp_server.BoundTools(ws, clock, on_event=trace.event, validate_fn=validate_fn)
        hook = guard.make_hook(ws, on_event=trace.event)
        if query_fn is None:
            from claude_agent_sdk import query as query_fn  # noqa: PLC0415
        options = sdk_options(ws, opts.model, hook, mcp_server.build_server(bound), opts.max_turns, opts.max_usd)
        task = prompt.task_prompt(len(opts.briefs), opts.max_minutes)
        trace.event("prompt", task)
        state = _phase(query_fn, task, options, trace, opts.max_minutes, "build")
        t_agent = time.monotonic() - t0
        review_info = review_and_fix(ws, opts, trace, query_fn, state, bound, workspace_root) if opts.review else {"ran": False}
        t_review = time.monotonic() - t0 - t_agent
        report = finalize(ws, opts, trace, freya_mod=freya_mod, validate_fn=validate_fn)
        report["review"] = review_info
        report["agent"] = {**_result_summary(state["result"]), "messages": state["messages"],
                           "timed_out": state["timed_out"], "error": state["error"]}
        report["timings"] = {"agent_s": round(t_agent), "review_and_fix_s": round(t_review), "total_s": round(time.monotonic() - t0)}
    except Exception as e:  # noqa: BLE001
        report = {"status": "failed", "slot": opts.slot, "message": f"builder error: {e!r}"}
        trace.event("error", report["message"])
    finally:
        report["trace"] = str(trace.dir)
        report["model"] = opts.model
        if opts.keep_workspace:
            report["workspace"] = str(ws)
        Path(opts.out_dir).mkdir(parents=True, exist_ok=True)
        (Path(opts.out_dir) / "build_report.json").write_text(json.dumps(report, indent=1, default=str) + "\n")
        trace.close({"status": report.get("status"), "saved": report.get("saved"), "fallback_used": report.get("fallback_used"),
                     "lint": {k: v for k, v in (report.get("lint") or {}).items() if k != "warning_list"},
                     "validate": report.get("validate"), "agent": report.get("agent"), "message": report.get("message"),
                     "review": {k: v for k, v in (report.get("review") or {}).items() if k in ("ran", "review_rules", "findings", "kinds", "fix_ran")}})
        if not opts.keep_workspace:
            shutil.rmtree(ws, ignore_errors=True)
    return report
