import copy
import json

import pytest

from builder.eval import score_policy
from tests.agentic.conftest import REPO

CONFIGS = sorted((REPO / "testbed").glob("**/config.json")) + sorted((REPO / "testbed" / "configs").glob("*.json"))


@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.parent.name if p.name == "config.json" else p.stem)
def test_config_against_itself_is_100(path):
    cfg = json.loads(path.read_text())
    result = score_policy.score(cfg, cfg)
    assert result["percent"] == 100.0 and result["total"] > 40


def test_one_changed_field_is_reported():
    cfg = json.loads((REPO / "testbed" / "configs" / "brief-a.config.json").read_text())
    pol = copy.deepcopy(cfg)
    pol["bands"][1]["attempts"] = 9
    result = score_policy.score(pol, cfg)
    bad = [r for r in result["rows"] if r["status"] != "match"]
    assert [r["field"] for r in bad] == ["bands.1.attempts"] and result["matched"] == result["total"] - 1


def test_normalisation():
    cfg = {"holidays": ["2031-01-01", "2031-03-14"], "queue_map": {"human": "Desk_X", "support": None},
           "identity": {"max_wrong": 3, "questions": ["a", "b"]}, "sentences": {"ai": "Example Bank's automated assistant"}}
    pol = {"holidays": ["2031-03-14", "2031-01-01"], "queue_map": {"human": " desk_x "},
           "identity": {"max_wrong": 3.0, "questions": ["b", "a"]}, "sentences": {"ai": "the automated assistant of Example Bank"},
           "_overrides": [{"key": "x"}], "extra": 1}
    rows = {r["field"]: r["status"] for r in score_policy.score(pol, cfg)["rows"]}
    assert rows == {"holidays": "match", "queue_map.human": "match", "queue_map.support": "match",
                    "identity.max_wrong": "match", "identity.questions": "mismatch",  # order matters for questions
                    "sentences.ai": "match"}
    assert score_policy.score(pol, cfg)["extra_fields"] == ["extra"]


def test_cli(tmp_path, capsys):
    cfg = REPO / "testbed" / "configs" / "brief-a.config.json"
    assert score_policy.main([str(cfg), str(cfg), "--only-problems"]) == 0
    assert "(100.0%)" in capsys.readouterr().out
