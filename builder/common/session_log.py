"""The Claude Code session log of an agentic builder run, copied next to our trace with secrets redacted.

Claude Code writes every session to ~/.claude/projects/<working directory with every non-alphanumeric character replaced by '-'>/<session id>.jsonl.
The builder's workspace is a temporary directory, so its sessions are found by that name after the run. Nothing here reads any other project's logs."""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

PATTERNS = [re.compile(p) for p in (r"sk-ant-[A-Za-z0-9_-]{8,}", r"sk-[A-Za-z0-9_-]{20,}", r"fak_[A-Za-z0-9_-]{8,}", r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{16,}",
                                    r"(?i)(?:api[_-]?key|secret|token|password)\"?\s*[:=]\s*\"?[A-Za-z0-9._~+/=-]{16,}")]
SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", re.I)


def secret_values(env=None) -> list[str]:
    env = os.environ if env is None else env
    vals = {v.strip() for k, v in env.items() if SECRET_NAME.search(k) and len(v.strip()) >= 12}
    envfile = Path(__file__).resolve().parents[2] / ".env"
    if envfile.exists():
        for line in envfile.read_text(errors="ignore").splitlines():
            if "=" in line and not line.lstrip().startswith("#") and SECRET_NAME.search(line.split("=", 1)[0]):
                v = line.split("=", 1)[1].strip().strip("\"'")
                if len(v) >= 12:
                    vals.add(v)
    return sorted(vals, key=len, reverse=True)


def redact(text: str, values=None) -> str:
    for v in (secret_values() if values is None else values):
        text = text.replace(v, "[REDACTED]")
    for p in PATTERNS:
        text = p.sub("[REDACTED]", text)
    return text


def project_dir(cwd: str | Path, home: Path | None = None) -> Path:
    real = os.path.realpath(str(cwd))
    return (home or Path.home()) / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", real)


def copy_session_logs(workspace: str | Path, trace_dir: str | Path, home: Path | None = None, values=None) -> list[str]:
    """Copy (redacted) the session jsonl files of one workspace into <trace_dir>/claude-session/. Returns the file names; [] when there are none."""
    src = project_dir(workspace, home)
    if not src.is_dir():
        return []
    dst = Path(trace_dir) / "claude-session"
    dst.mkdir(parents=True, exist_ok=True)
    vals = secret_values() if values is None else values
    out = []
    for f in sorted(src.glob("*.jsonl")):
        (dst / f.name).write_text(redact(f.read_text(errors="replace"), vals), encoding="utf-8")
        out.append(f.name)
    return out
