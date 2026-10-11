"""local_sim shared budget: one counter with a cap, N concurrency slots, one STOP file. Temp dir, no model, no network."""
import importlib.util
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if not (REPO / "vendor" / "build-the-builder").exists():
    pytest.skip("local_sim needs the vendor kit (see README_RUN.md)", allow_module_level=True)


@pytest.fixture
def ls(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("local_sim_under_test", REPO / "scripts" / "local_sim.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setattr(m, "BUDGET", tmp_path / "_budget")
    monkeypatch.setattr(m, "TOTAL_CAP", 3)
    monkeypatch.setattr(m, "SLOTS", 2)
    m.STOP = m._Stop()
    return m


def test_the_counter_stops_at_the_cap(ls):
    assert [ls.budget_claim() for _ in range(5)] == [1, 2, 3, None, None]


def test_at_most_slots_run_at_the_same_time(ls):
    running, peak, lock = [0], [0], threading.Lock()

    def work():
        with ls.Slot():
            with lock:
                running[0] += 1
                peak[0] = max(peak[0], running[0])
            time.sleep(0.15)
            with lock:
                running[0] -= 1
    ts = [threading.Thread(target=work) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert peak[0] == 2


def test_the_stop_file_stops_every_process_and_blocks_slots(ls):
    assert not ls.STOP.is_set()
    other = ls._Stop()                      # another process: it only sees the file
    ls.STOP.set("test warning")
    assert other.is_set() and (ls.BUDGET / "STOP").read_text().endswith("test warning\n")
    with pytest.raises(ls.LimitHit):
        with ls.Slot():
            pass
