"""Nothing brief-specific may appear in what the builder agent reads: the skill, the task prompt, the templates and
the pattern_demo example copied into its workspace. The blacklist comes from the testbed configs (kit briefs and fake
briefs); generic vocabulary the kit itself uses, the policy schema's canonical keys and the explicit allow-list are
removed from it."""

import datetime
import json
import re

import pytest

from tests.agentic.conftest import REPO

SKILL = REPO / "builder" / "agentic" / "skill"
SCANNED = sorted(p for p in SKILL.rglob("*") if p.is_file() and "__pycache__" not in p.parts) + [
    REPO / "builder" / "agentic" / "prompt.py",
    REPO / "tests" / "agentic" / "fixtures" / "pattern_demo.workflow.json",
    REPO / "tests" / "agentic" / "fixtures" / "pattern_demo.openapi.json",
]
CONFIGS = sorted((REPO / "testbed" / "configs").glob("*.json")) + sorted((REPO / "testbed" / "fake_briefs").glob("*/config.json"))


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def _dates(iso_dates) -> set[str]:
    out = set()
    for h in iso_dates:
        d = datetime.date.fromisoformat(h)
        out |= {h, f"{d.day} {d:%B}", f"{d:%B} {d.day}", f"{d:%d.%m.%y}"}
    return out


def kit_brief_terms() -> set[str]:
    """Brief A/B's bank name and holidays: always blacklisted, even though the kit's own files name the bank."""
    terms = set()
    for path in sorted((REPO / "testbed" / "configs").glob("brief-*.config.json")):
        c = json.loads(path.read_text())
        terms |= {c["bank"]} | _dates(c["holidays"])
    return terms


def blacklist() -> set[str]:
    terms = set()
    for path in CONFIGS:
        c = json.loads(path.read_text())
        terms.add(c["bank"])
        terms |= _dates(c["holidays"])
        for key in ("outcome_map", "queue_map", "note_map", "tools", "account_fields"):
            terms |= set(_strings(c[key]))
        terms |= set(c["identity"]["questions"])
        terms |= {pt["enum"] for pt in c["product_types"].values()}
        terms |= {s for s in _strings(c["sentences"]) if len(s.split()) > 6}
    kit = (REPO / "tools" / "openapi.json").read_text().lower() + "".join(
        p.read_text().lower() for p in (REPO / "docs").glob("*.md"))
    schema = (SKILL / "build-collections-agent" / "reference" / "policy-schema.md").read_text()
    canonical = set(re.findall(r'`"?([a-z_][a-z0-9_]*)"?`', schema)) | set(re.findall(r'"([a-z_][a-z0-9_]*)"', schema))
    allow = set(json.loads((REPO / "tests" / "agentic" / "no_leak_allowlist.json").read_text())["allow"])
    generic = {t for t in terms if t and t.lower() not in kit and t not in canonical and t not in allow}
    return generic | kit_brief_terms()


def test_blacklist_has_the_brief_specific_values():
    black = blacklist()
    for must in ("Freya Bank", "Halden Savings", "2026-10-26", "26 October", "postcode", "amount_cents", "10-PTP", "welfare"):
        assert must in black, must
    assert "promise" not in black and "verify_identity" not in black  # kit vocabulary stays usable


@pytest.mark.parametrize("path", SCANNED, ids=lambda p: str(p.relative_to(REPO)))
def test_no_brief_value_in_builder_material(path):
    text = path.read_text(encoding="utf-8")
    hits = [t for t in sorted(blacklist()) if re.search(r"(?<![A-Za-z0-9_])" + re.escape(t) + r"(?![A-Za-z0-9_])", text, re.I)]
    assert hits == [], f"{path.name} contains brief-specific values: {hits}"


def test_allowlist_entries_are_justified():
    allow = json.loads((REPO / "tests" / "agentic" / "no_leak_allowlist.json").read_text())["allow"]
    assert all(isinstance(v, str) and len(v) > 20 for v in allow.values())
    assert not any(re.search(r"\d", k) or " " in k for k in allow)  # never a date, code or sentence
