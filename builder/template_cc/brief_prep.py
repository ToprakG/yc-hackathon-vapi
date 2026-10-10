"""Raw-material preprocessing for the extractor (generic, no brief values).

Some briefs are email threads, memos over a policy or code lists. `prepare(text)` makes the order and the overrides
explicit before the model reads it:
- an email thread (From:/Sent:/Date:/Subject: headers, "-----Original Message-----", "On ... wrote:") is split into messages,
  put in time order, oldest first, each prefixed `[Message k of n - later messages override earlier ones]`; quoted `>` lines
  that repeat text already in the thread are removed;
- a memo or amendment section gets an `[Override]` line before it;
- a text with none of these markers is returned unchanged (byte for byte).
The extractor keeps the original text for its quote checks: quotes must match the brief as written.
"""

from __future__ import annotations

import datetime as dt
import re

HEADER = re.compile(r"^(From|Sent|Date|To|Cc|Subject):", re.I)
SPLIT = re.compile(r"^(-{3,}\s*Original Message\s*-{3,}|On .{5,120} wrote:)\s*$", re.I)
QUOTED = re.compile(r"^\s*>+ ?(.*)$")
OVERRIDE_HEADING = re.compile(r"^\s*(#{1,6}\s*)?[^\n]*\b(memo|amendments?)\b", re.I)
SUPERSEDES = re.compile(r"\b(supersedes|superseded by|supersede)\b", re.I)
DATE_FORMATS = ("%d %B %Y %H:%M", "%d %B %Y", "%B %d, %Y %H:%M", "%B %d, %Y", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y %H:%M",
                "%d/%m/%Y", "%a, %d %b %Y %H:%M", "%d %b %Y %H:%M", "%d %b %Y")


def _is_thread(lines: list[str]) -> bool:
    headers = sum(1 for l in lines if re.match(r"^(From|Sent):", l, re.I))
    return headers >= 2 or any(SPLIT.match(l.strip()) for l in lines) or sum(1 for l in lines if QUOTED.match(l)) >= 2


def _parse_date(block: list[str]):
    for l in block[:8]:
        m = re.match(r"^(Sent|Date):\s*(.+?)\s*$", l, re.I)
        if not m:
            continue
        raw = re.sub(r"\s*\(.*?\)\s*$", "", m.group(2))
        for f in DATE_FORMATS:
            try:
                return dt.datetime.strptime(raw, f)
            except ValueError:
                pass
    return None


def _messages(lines: list[str]) -> list[list[str]]:
    """Split at a From: header that starts a header block, at an Original Message line and at an 'On ... wrote:' line."""
    msgs: list[list[str]] = [[]]
    for i, l in enumerate(lines):
        starts = bool(SPLIT.match(l.strip()))
        if re.match(r"^From:", l, re.I) and (i == 0 or not re.match(r"^(From|Sent|Date|To|Cc|Subject):", lines[i - 1], re.I)):
            starts = True
            if i > 0 and SPLIT.match(lines[i - 1].strip()):
                starts = False  # the separator line already opened this message
        if starts and any(x.strip() for x in msgs[-1]):
            msgs.append([])
        if not SPLIT.match(l.strip()):
            msgs[-1].append(l)
    return [m for m in msgs if any(x.strip() for x in m)]


def _drop_quoted_repeats(text: str) -> str:
    plain = {" ".join(l.lower().split()) for l in text.splitlines() if not QUOTED.match(l) and l.strip()}
    keep = []
    for l in text.splitlines():
        m = QUOTED.match(l)
        if m and " ".join(m.group(1).lower().split()) in plain | {""}:
            continue
        keep.append(l)
    return "\n".join(keep)


def _thread(text: str) -> str:
    lines = _drop_quoted_repeats(text).splitlines()
    msgs = _messages(lines)
    if len(msgs) < 2:
        return text
    dates = [_parse_date(m) for m in msgs]
    if all(d is not None for d in dates):
        order = sorted(range(len(msgs)), key=lambda i: dates[i])
    else:
        order = list(range(len(msgs)))[::-1]  # a reply chain lists the newest message first
    n = len(msgs)
    out = []
    for k, i in enumerate(order, 1):
        out.append(f"[Message {k} of {n} - later messages override earlier ones]")
        out.append("\n".join(msgs[i]).strip("\n"))
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def _overrides(text: str) -> str:
    out, changed = [], False
    for l in text.splitlines():
        if (re.match(r"^\s*(#{1,6}\s+|[A-Z][A-Z \-:]{6,}$)", l) and OVERRIDE_HEADING.match(l)) or SUPERSEDES.search(l):
            out.append("[Override] The memo or amendment below replaces earlier statements where they differ.")
            changed = True
        out.append(l)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "") if changed else text


def prepare(text: str) -> str:
    lines = text.splitlines()
    out = text
    if _is_thread(lines):
        out = _thread(text)
    return _overrides(out)
