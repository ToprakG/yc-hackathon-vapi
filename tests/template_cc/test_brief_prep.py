from pathlib import Path

from builder.template_cc.brief_prep import prepare

REPO = Path(__file__).resolve().parents[2]

THREAD = """From: Ana Invented <ana@example.test>
To: Team
Subject: RE: RE: rules
Date: 3 March 2031

Change of plan: the callback window ends at 17:00.

> Callbacks are 10:00 to 18:00.

-----Original Message-----
From: Bo Invented
Sent: 2 March 2031 09:00

Callbacks are 10:00 to 18:00.
Three wrong answers end the check.

-----Original Message-----
From: Cy Invented
Sent: 1 March 2031 08:00

Please call people about late payments.
"""


def test_a_plain_brief_is_unchanged():
    for name in ("brief-a.md", "brief-b.md"):
        text = (REPO / "briefs" / name).read_text()
        assert prepare(text) == text


def test_thread_is_ordered_oldest_first_prefixed_and_quoted_duplicates_removed():
    out = prepare(THREAD)
    marks = [l for l in out.splitlines() if l.startswith("[Message ")]
    assert marks == [f"[Message {k} of 3 - later messages override earlier ones]" for k in (1, 2, 3)]
    assert out.index("Please call people") < out.index("Three wrong answers") < out.index("the callback window ends at 17:00")
    assert "> Callbacks are 10:00 to 18:00." not in out
    assert out.count("Callbacks are 10:00 to 18:00.") == 1


def test_a_reply_chain_without_dates_is_reversed():
    text = "Latest answer: yes.\n\nOn Mon, Bo wrote:\n\nMiddle: maybe.\n\nOn Sun, Cy wrote:\n\nFirst: question?\n"
    out = prepare(text)
    assert out.index("First: question?") < out.index("Middle: maybe.") < out.index("Latest answer: yes.")


def test_memo_sections_are_marked():
    text = "# Policy\n\nEverything is 5 days.\n\n## INTERNAL MEMO - amendments\n\nNow it is 7 days.\n"
    out = prepare(text)
    assert out.count("[Override]") == 1 and out.index("[Override]") < out.index("## INTERNAL MEMO")
    assert out.endswith("Now it is 7 days.\n")
    assert prepare("This replaces nothing and mentions memo only in text.\n") == "This replaces nothing and mentions memo only in text.\n"


def test_the_kit_memo_and_email_briefs_are_prepared():
    f5 = (REPO / "testbed/fake_briefs/f5-halden-email/brief.md").read_text()
    out = prepare(f5)
    assert out.startswith("[Message 1 of ") and out.count("[Message ") >= 3
    assert out.index("Re recording promises") < out.index("Pulling the thread together")
    f6 = (REPO / "testbed/fake_briefs/f6-corvid-memo/brief.md").read_text()
    assert prepare(f6).count("[Override]") == 1
