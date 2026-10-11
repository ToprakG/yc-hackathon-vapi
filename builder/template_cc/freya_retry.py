"""Our wrapper around the kit's freya.py (which does not retry), and the Freya-outage signature.

install(freya_module): GET and PUT calls that fail with a 5xx are tried 3 times, 10 s apart. POST is never retried (a repeated create
could start a second simulation or workflow). Idempotent: installing twice wraps once.

is_outage(rows): a run in which NO customer made any tool call is a Freya outage, not an agent failure (a working agent calls at least
the identity tool in every case). Such a run is reported MISSING for all cases and is never counted as a pass or a fail.
"""

from __future__ import annotations

import re
import time

TRIES, PAUSE_S = 3, 10
_5XX = re.compile(r"->\s*5\d\d\b")


def install(freya_module, sleep=time.sleep):
    original = freya_module.api
    if getattr(original, "_tcc_retry", False):
        return freya_module

    def api(method, path, body=None, **params):
        for attempt in range(1, TRIES + 1):
            try:
                return original(method, path, body, **params)
            except RuntimeError as e:
                retryable = method.upper() in ("GET", "PUT") and _5XX.search(str(e))
                if not retryable or attempt == TRIES:
                    raise
                sleep(PAUSE_S)

    api._tcc_retry = True
    freya_module.api = api
    return freya_module


def is_outage(rows: list[dict]) -> bool:
    return bool(rows) and all(not (r.get("tools") or []) for r in rows)
