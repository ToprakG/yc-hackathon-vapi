"""Ingest a case folder into one brief text + a tool API file.     python3 -m builder.ingest <case_folder> <mock_url> <out_dir>

Order: BRIEF.md, README.md, then every other file (sorted; announcements / Q&A come after on purpose: they may change rules). Each file is converted to text:
md/txt as is; docx (python-docx, pandoc as fallback; tables -> markdown); pdf (pdftotext, pypdf as fallback); xlsx/xlsm (openpyxl, every sheet -> markdown table);
csv -> markdown table; html -> text; json/yaml that is not an OpenAPI file -> as text. Images / archives / other binaries are listed in the notes, not read.
Headers "=== FILE: name ===" separate the files. Tool API: GET <mock_url>/openapi.json, else an OpenAPI json/yaml file in the folder.
"""
from __future__ import annotations

import csv
import io
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

FIRST = ("brief.md", "readme.md")
TEXT = {".md", ".txt", ".markdown", ".rst"}
SKIP = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".zip", ".gz", ".mp3", ".wav", ".mp4", ".ds_store"}


def _md_table(rows) -> str:
    rows = [[("" if c is None else str(c)).replace("\n", " ").replace("|", "/").strip() for c in r] for r in rows]
    rows = [r for r in rows if any(r)]
    if not rows:
        return ""
    w = max(len(r) for r in rows)
    rows = [r + [""] * (w - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * w]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(out)


def read_docx(p: Path) -> str:
    try:
        import docx  # noqa: PLC0415
        d = docx.Document(str(p))
        from docx.table import Table  # noqa: PLC0415
        from docx.text.paragraph import Paragraph  # noqa: PLC0415
        out = []
        for el in d.element.body.iterchildren():   # document order: paragraphs and tables interleaved
            if el.tag.endswith("}p"):
                para = Paragraph(el, d)
                t = para.text.strip()
                if t:
                    st = (para.style.name or "") if para.style is not None else ""
                    out.append(("#" * int(st[-1]) + " " + t) if st.startswith("Heading ") and st[-1].isdigit() else t)
            elif el.tag.endswith("}tbl"):
                out.append(_md_table([[c.text for c in r.cells] for r in Table(el, d).rows]))
        return "\n\n".join(x for x in out if x)
    except Exception:  # noqa: BLE001
        if shutil.which("pandoc"):
            return subprocess.run(["pandoc", "-t", "gfm", str(p)], capture_output=True, text=True, timeout=60).stdout
        raise


def read_pdf(p: Path) -> str:
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", "-layout", str(p), "-"], capture_output=True, text=True, timeout=120)
        if r.stdout.strip():
            return r.stdout
    from pypdf import PdfReader  # noqa: PLC0415
    return "\n\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)


def read_xlsx(p: Path) -> str:
    import openpyxl  # noqa: PLC0415
    wb = openpyxl.load_workbook(str(p), data_only=True, read_only=True)
    out = []
    for ws in wb.worksheets:
        t = _md_table(list(ws.iter_rows(values_only=True)))
        if t:
            out.append(f"### Sheet: {ws.title}\n\n{t}")
    return "\n\n".join(out)


def read_csv(p: Path) -> str:
    raw = p.read_text(encoding="utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(raw[:4000])
    except csv.Error:
        dialect = csv.excel
    return _md_table(list(csv.reader(io.StringIO(raw), dialect)))


def read_html(p: Path) -> str:
    s = p.read_text(encoding="utf-8", errors="replace")
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h\d)>", "\n", s)
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"<[^>]+>", " ", s))


def to_text(p: Path) -> str | None:
    ext = p.suffix.lower()
    if ext in SKIP or p.name.startswith("."):
        return None
    if ext in TEXT or ext in (".json", ".yaml", ".yml"):
        return p.read_text(encoding="utf-8", errors="replace")
    if ext == ".docx":
        return read_docx(p)
    if ext == ".pdf":
        return read_pdf(p)
    if ext in (".xlsx", ".xlsm"):
        return read_xlsx(p)
    if ext == ".csv":
        return read_csv(p)
    if ext in (".html", ".htm"):
        return read_html(p)
    try:
        return p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def _openapi_of(p: Path):
    try:
        if p.suffix.lower() == ".json":
            d = json.loads(p.read_text(encoding="utf-8"))
        elif p.suffix.lower() in (".yaml", ".yml"):
            import yaml  # noqa: PLC0415
            d = yaml.safe_load(p.read_text(encoding="utf-8"))
        else:
            return None
    except Exception:  # noqa: BLE001
        return None
    return d if isinstance(d, dict) and "openapi" in d and d.get("paths") else None   # an empty spec is no tool API


def fetch_openapi(mock_url: str):
    req = urllib.request.Request(mock_url.rstrip("/") + "/openapi.json", headers={"user-agent": "Mozilla/5.0 (builder)", "accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    return d if isinstance(d, dict) and "openapi" in d and d.get("paths") else None   # a spec without paths is no tool API


def ingest(folder: Path, mock_url: str, out: Path) -> dict:
    folder, out = Path(folder), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    def order(p):   # BRIEF.md, README.md, then undated files, then dated files oldest -> newest (a later document may override an earlier one)
        rel = str(p.relative_to(folder)).lower()
        m = re.search(r"(\d{4}-\d{2}-\d{2})", rel)
        return (0 if p.name.lower() == FIRST[0] else 1 if p.name.lower() == FIRST[1] else 2, 1 if m else 0, m.group(1) if m else "", rel)
    files = sorted((p for p in folder.rglob("*") if p.is_file() and not any(part.startswith(".") for part in p.relative_to(folder).parts)), key=order)
    notes, parts, api, api_src = [], [], None, None
    for p in files:
        rel = str(p.relative_to(folder))
        oa = _openapi_of(p)
        if oa is not None:
            api, api_src = api or oa, api_src or rel
            notes.append(f"{rel}: OpenAPI file (tool API fallback), not part of the brief text")
            continue
        try:
            t = to_text(p)
        except Exception as e:  # noqa: BLE001
            notes.append(f"{rel}: CONVERSION FAILED ({type(e).__name__}: {str(e)[:80]})")
            continue
        if t is None or not t.strip():
            notes.append(f"{rel}: skipped (binary or empty)")
            continue
        parts.append(f"=== FILE: {rel} ===\n\n{t.strip()}\n")
        notes.append(f"{rel}: {len(t)} chars")
    try:
        live = fetch_openapi(mock_url) if mock_url else None
    except Exception as e:  # noqa: BLE001
        live = None
        notes.append(f"GET {mock_url}/openapi.json failed ({type(e).__name__}); looking in the folder")
    if live is not None:
        api, api_src = live, f"{mock_url.rstrip('/')}/openapi.json"
    if api is None:
        raise RuntimeError("no tool API: {mock_url}/openapi.json is unavailable and the folder has no OpenAPI file")
    servers = [s for s in api.get("servers") or [] if isinstance(s, dict) and str(s.get("url", "")).startswith("http")]
    if not servers and mock_url:   # no usable server URL in the spec: tools go to the mock URL
        api["servers"] = [{"url": mock_url.rstrip("/")}]
        notes.append(f"openapi has no absolute servers[].url: set to {mock_url.rstrip('/')}")
    brief = out / "case_brief.md"
    note = ("NOTE: the sections below are separate documents of one case folder (=== FILE: name ===). BRIEF.md and README.md come first; the other files follow, "
            "dated files oldest to newest. The documents were written at different times and may disagree: a later-dated document overrides an earlier one "
            "(announcements, mails and meeting notes after the analysis). Record each override you apply.\n")
    brief.write_text(note + "\n" + "\n".join(parts), encoding="utf-8")
    api_path = out / "tools.openapi.json"
    api_path.write_text(json.dumps(api, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "ingest_notes.txt").write_text("\n".join(notes) + f"\ntool API from: {api_src}\n", encoding="utf-8")
    return {"brief": str(brief), "api": str(api_path), "notes": notes, "api_source": api_src, "files": len(parts), "chars": brief.stat().st_size}


if __name__ == "__main__":
    r = ingest(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]))
    print(json.dumps({k: r[k] for k in ("brief", "api", "files", "chars", "api_source")}))
    print("\n".join(r["notes"]))
