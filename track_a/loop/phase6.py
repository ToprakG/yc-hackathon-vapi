"""Phase 6: report BEST. Score holdout only when holdout tasks exist."""

from __future__ import annotations

from pathlib import Path

from loop.paths import shared, track_b
from loop.schema import load_json
from loop.store import load_development_tasks


def run_phase6(root: Path) -> int:
    print("Development:")
    for task in load_development_tasks(root):
        best_path = shared(root) / "versions" / task["id"] / "BEST"
        best = best_path.read_text().strip() if best_path.exists() else "missing"
        decision_path = shared(root) / "versions" / task["id"] / "v2" / "gate_decision.json"
        if decision_path.exists():
            decision = load_json(decision_path)
            print(f"  {task['id']}: BEST={best} gate={decision['decision']} ({decision['reason']})")
        else:
            print(f"  {task['id']}: BEST={best} (no patch reached the gate)")
    holdout = track_b(root) / "tasks" / "holdout"
    tasks = sorted(path.name for path in holdout.glob("*.json")) if holdout.exists() else []
    if not tasks:
        print("Holdout has no tasks. V1 and BEST were not scored on holdout.")
        return 0
    print(f"Holdout tasks present: {', '.join(tasks)}")
    print("Holdout scoring needs a locked task file. None were run in this pass.")
    return 0
