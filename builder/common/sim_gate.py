"""One Freya simulation at a time per workspace: before this builder starts simulations, make sure none is running (another user may share the workspace)."""
from __future__ import annotations

import datetime
import sys
import time


def running_simulations(freya) -> list[tuple]:
    r = freya.api("GET", "/api/v2/simulations", workspaceId=freya.workspace_id(), limit=15)
    now = datetime.datetime.now(datetime.timezone.utc)
    out = []
    for s in (r.get("simulations") or r.get("items") or r):
        if str(s.get("status")) in ("running", "queued", "pending", "in_progress"):
            created = datetime.datetime.fromisoformat(s["createdAt"].replace("Z", "+00:00"))
            out.append((s.get("name"), round((now - created).total_seconds() / 60, 1), str(s["id"])[:8]))
    return out


def wait_until_idle(freya, trace=None, max_wait_s: float = 600, poll_s: float = 15, sleep=time.sleep, say=None) -> bool:
    """True when no simulation is running. While one is, say so loudly (stderr + trace) every poll and wait up to max_wait_s; it never cancels anything.
    A failing list call counts as idle (it must not stop a build)."""
    say = say or (lambda m: print(m, file=sys.stderr, flush=True))
    end = time.monotonic() + max_wait_s
    while True:
        try:
            r = running_simulations(freya)
        except Exception:  # noqa: BLE001
            return True
        if not r:
            return True
        msg = f"SIMULATION RUNNING IN THE WORKSPACE ({', '.join(f'{n!r} {a} min' for n, a, _ in r)}): ask the other user to pause; waiting before starting this build's simulation"
        say(msg)
        if trace is not None:
            trace.event("sim_gate", msg)
        if time.monotonic() >= end:
            return False
        sleep(poll_s)
