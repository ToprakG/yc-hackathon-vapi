"""policy.language 'tr': every sentence the code speaks is Turkish; English stays byte-identical. Lines from the brief are untouched."""
import json
from pathlib import Path

from builder.template_cc import compiler
from builder.template_cc.apimodel import ApiModel
from builder.template_cc.compiler import i18n

REPO = Path(__file__).resolve().parents[2]
GOLD = Path(__file__).resolve().parent / "golden"
FEATS = "f1,f2,f3,f4,f7,f8,f9,f11,f12,f13,f24_day_once,f33_attempt_ladder"


def build(lang):
    pol = json.loads((GOLD / "brief-a.policy.json").read_text())
    pol["language"] = lang
    wf, _ = compiler.compile(pol, ApiModel.load(REPO / "tools" / "openapi.json"), features=FEATS)
    return wf, pol


def codes(wf):
    return json.dumps(wf, ensure_ascii=False)


def test_english_unchanged():
    wf, _ = build("en")
    text = codes(wf)
    assert "Which amount would you like to pay?" in text and "Pazartesi" not in text


def test_turkish_code_texts_and_dates():
    wf, pol = build("tr")
    text = codes(wf)
    for en, _ in i18n.TR:
        if en.startswith("'") or en.startswith("money"):
            assert en not in text, en
    assert "Pazartesi" in text and "Ocak" in text and "'Monday'" not in text
    assert "Always speak Turkish" in text


def test_unknown_language_is_unchanged():
    assert i18n.localize("'Goodbye.'", "xx") == "'Goodbye.'"


def test_default_lines_follow_the_language():
    from builder.template_cc import policy_check
    pol = {"language": "tr", "address": "{title} {last_name}", "sentences": {"opening": "Freya Bank'tan arıyorum"}}
    lines = policy_check.default_lines(pol)
    assert lines["right_party_question"]["text"] == "{title} {last_name} ile mi görüşüyorum?"
    assert lines["opening"]["text"].startswith("Merhaba, Freya Bank")
    assert lines["goodbye"]["text"].endswith("İyi günler.")
    en = policy_check.default_lines({"language": "en", "address": "Mr Reyes", "sentences": {}})
    assert en["goodbye"]["text"].endswith("Goodbye.")
