"""F20: once-rules are code flags (said_once)."""
from builder.template_cc.compiler import runtime as RT


def test_said_once_is_true_once_per_line_id():
    v = {}
    assert RT.said_once(v, "id_reason") is True
    assert v["said_id_reason"] == "1"
    assert RT.said_once(v, "id_reason") is False
    assert RT.said_once(v, "hardship_sympathy") is True  # another line is independent


def test_said_once_honours_the_key_the_verifier_reads():
    assert RT.said_once({"said_hardship_sympathy": "1"}, "hardship_sympathy") is False
