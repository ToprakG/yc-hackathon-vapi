from pathlib import Path

TRACK_A = Path(__file__).resolve().parents[1]
ROOT = TRACK_A.parent


def track_b(root: Path) -> Path:
    return root / "track_b"


def shared(root: Path) -> Path:
    return root / "shared"
