"""Is any Freya simulation running in the workspace?   python3 scripts/sim_idle.py [--wait SECONDS]
Exit 0 = none running (safe to start the final build's simulations); exit 1 = at least one running/queued (prints name, age, id): tell the other user to pause.
With --wait N it polls every 15 s for up to N seconds before giving up. Read-only: it never cancels anything."""
import datetime, os, sys, time
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
V = REPO / "vendor" / "build-the-builder"
for p in (str(REPO), str(V / "tools" / "driver"), str(V / "tools"), str(V)):
    sys.path.insert(0, p)
for line in (REPO / ".env").read_text().splitlines() if (REPO / ".env").exists() else []:
    line = line.strip().removeprefix("export ")
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        if v.strip() and not os.environ.get(k.strip()):
            os.environ[k.strip()] = v.strip().strip("\"'")
import freya  # noqa: E402


def running():
    r = freya.api("GET", "/api/v2/simulations", workspaceId=freya.workspace_id(), limit=15)
    now = datetime.datetime.now(datetime.timezone.utc)
    out = []
    for s in (r.get("simulations") or r.get("items") or r):
        if str(s.get("status")) in ("running", "queued", "pending", "in_progress"):
            created = datetime.datetime.fromisoformat(s["createdAt"].replace("Z", "+00:00"))
            out.append((s.get("name"), round((now - created).total_seconds() / 60, 1), s["id"][:8], s.get("status")))
    return out


wait = int(sys.argv[sys.argv.index("--wait") + 1]) if "--wait" in sys.argv else 0
end = time.time() + wait
while True:
    try:
        r = running()
    except Exception as e:  # noqa: BLE001
        print(f"sim_idle: cannot read the simulation list ({e}); treat as UNKNOWN"); sys.exit(2)
    if not r:
        print("sim_idle: no simulation running in the workspace"); sys.exit(0)
    if time.time() >= end:
        for n, a, i, st in r:
            print(f"sim_idle: RUNNING  {st}  {n!r}  {a} min old  ({i})")
        print("sim_idle: tell the other user to pause their simulations; this script never cancels anything"); sys.exit(1)
    time.sleep(15)
