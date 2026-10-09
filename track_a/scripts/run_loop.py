import sys
from pathlib import Path

TRACK_A = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRACK_A))

from loop.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
