from builder.agentic.tools import coverage

BRIEF = """# Example Bank brief

1. **Identity first.** Ask the date of birth, then the code word.
2. Never mention the balance before identity is verified.
3. Callbacks run from 09:00 to 17:00.

The assistant says: “You’ll get a letter confirming this.”
"""


def rule(**kw):
    base = {"id": "R1", "kind": "rule", "statement": "s", "source_quote": "Ask the date of birth, then the code word",
            "overridden_by": None, "implemented_in": ["node:identity"]}
    return {**base, **kw}


def errors(rules, wf, **kw):
    return [e["msg"] for e in coverage.check(rules, wf, [BRIEF], **kw)["errors"]]


def test_good_rule_passes_and_normalisation_is_lenient(base_agent):
    base_agent["system_prompt"] = "You are the assistant of Example Bank."
    rules = [rule(), rule(id="R2", source_quote="identity first. ask the DATE of birth", implemented_in=["system_prompt"]),
             rule(id="R3", source_quote='"You\'ll get a letter confirming this."', implemented_in=["tool:workflow/close_call", "hook:workflow/close_call"]),
             rule(id="R4", source_quote="Callbacks run from 09:00", implemented_in=["transition:identity->collection", "tool:collection/create_promise"])]
    assert errors(rules, base_agent) == []


def test_quote_not_in_brief(base_agent):
    assert any("not found in the brief" in e for e in errors([rule(source_quote="Offer a 10% discount on request")], base_agent))


def test_assumption_may_quote_the_tool_api(base_agent):
    r = rule(kind="assumption", source_quote="The call may be repeated.")
    assert errors([r], base_agent, api_text="500: The service failed. The call may be repeated.") == []
    assert errors([r], base_agent) != []


def test_missing_target(base_agent):
    errs = errors([rule(implemented_in=["node:verify", "code:identity", "global:off_topic", "transition:a->b", "tool:collection/add_note"])], base_agent)
    assert len(errs) == 5 and any("no node 'verify'" in e for e in errs) and any("no code node 'identity'" in e for e in errs)


def test_na_needs_a_reason(base_agent):
    assert any("n/a without a reason" in e for e in errors([rule(implemented_in="n/a")], base_agent))
    assert errors([rule(implemented_in=["n/a"], reason="the tool API has no such field")], base_agent) == []
    assert any("not implemented" in e for e in errors([rule(implemented_in=[])], base_agent))


def test_numbered_lines_are_counted(base_agent):
    report = coverage.check([rule()], base_agent, [BRIEF])
    assert report["numbered_lines"] == 3 and report["numbered_cited"] == 1
    assert "1/3 numbered brief lines cited" in report["warnings"][0]["msg"]
