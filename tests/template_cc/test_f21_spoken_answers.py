"""F21: a spoken identity answer is normalised in code (digit-by-digit years, spelling alphabets in codes)."""
import copy
import json
from pathlib import Path

import pytest

from builder.template_cc import compiler
from builder.template_cc.apimodel import ApiModel
from builder.template_cc.compiler import runtime as R

from .helpers import call_vars, run_code

REPO = Path(__file__).resolve().parents[2]
GOLD = Path(__file__).resolve().parent / "golden"


@pytest.mark.parametrize("kind,text,value", [
    ("date", "The third of June, one nine five nine.", "1959-06-03"),
    ("date", "first of November one nine five five", "1955-11-01"),
    ("date", "7 March, two zero zero three", "2003-03-07"),
    ("year", "one nine nine five", "1995"),
    ("alnum_code", "Mike Golf nine seven, Tango Zulu.", "MG9 7TZ"),
    ("alnum_code", "L S six, two H Q", "LS6 2HQ"),
    ("date", "July sixteen nineteen sixty two", "1962-07-16"),  # a cardinal day after the month, said in two pieces
    ("date", "June twenty nineteen sixty two", "1962-06-20"),
    ("date", "the third of June nineteen fifty nine", "1959-06-03"),  # what already worked keeps working
])
def test_spoken_forms_are_complete_answers(kind, text, value):
    assert R.answer_from_spoken(kind, text) == (value, True)


@pytest.mark.parametrize("kind,text", [("date", "one nine five nine"), ("digits:4", "one nine five nine"), ("text", "Mike Golf")])
def test_other_kinds_and_incomplete_answers_are_left_alone(kind, text):
    assert R.spoken_forms("digits:4", text) == text and R.spoken_forms("text", text) == text
    assert R.answer_from_spoken(kind, text) == R.answer_from_speech(kind, text)


def build(features):
    pol = json.loads((GOLD / "brief-a.policy.json").read_text())
    api = ApiModel.load(REPO / "tools" / "openapi.json")
    wf, _ = compiler.compile(pol, api, features=features)
    return wf, pol


def test_id_check_uses_the_spoken_forms_only_when_the_flag_is_on():
    for feats, expect in (("f1,f21", "send"), ("f1", "ask")):
        wf, pol = build(feats)
        v = run_code(wf, "setup", call_vars(pol, "2031-03-05T10:00"))
        v["id_q"] = "date_of_birth"
        v["id_answer_text"] = "the third of June, one nine five nine"
        assert run_code(wf, "id_check", v)["id_route"] == expect


@pytest.mark.parametrize("kind,text,value", [
    ("date", "the fourth of May, one nine eight one, sorry, one nine eight two", "1982-05-04"),   # last spoken year wins
    ("date", "the fourth of May, one nine eight one, I mean the sixth of July nineteen ninety", "1990-07-06"),
    ("alnum_code", "M as in Mike, G as in Golf, nine seven, T for Tango, Z for Zulu", "MG9 7TZ"),
    ("alnum_code", "A like Alpha, B as in Bravo, one two, C for Charlie D for Delta", "AB1 2CD"),
])
def test_corrected_years_and_as_in_letters(kind, text, value):
    assert R.answer_from_spoken(kind, text) == (value, True)


@pytest.mark.parametrize("kind,text", [
    ("date", "the fourth of May nineteen eighty-"),   # cut off inside the year: not a complete answer
    ("year", "nineteen seventy-"),
    ("date", "the fourth of May nineteen sixty -"),
])
def test_a_year_cut_off_after_a_tens_word_is_incomplete(kind, text):
    assert R.answer_from_spoken(kind, text) == ("", False)


def test_a_full_hyphenated_year_still_counts():
    assert R.answer_from_spoken("date", "the fourth of May nineteen eighty-two") == ("1982-05-04", True)


def test_without_the_flag_the_cut_off_year_goes_the_old_way():
    for feats, expect in (("f1,f21", "ask"), ("f1", "send")):
        wf, pol = build(feats)
        v = run_code(wf, "setup", call_vars(pol, "2031-03-05T10:00"))
        v["id_q"] = "date_of_birth"
        v["id_answer_text"] = "the third of June nineteen sixty-"
        assert run_code(wf, "id_check", v)["id_route"] == expect
