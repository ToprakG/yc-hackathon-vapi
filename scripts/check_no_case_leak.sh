#!/bin/bash
# No-hardcode guard: the lines ADDED to the builder (builder/, scripts/ except mock/ case/ traces/ out/ submission/ and tests/) since the tag must not carry case content.
#   scripts/check_no_case_leak.sh [base-ref]      base default: final-submit.  Exit 1 + the offending added lines (file:line) on a hit. Prints counts + the first 20 hits only.
# Static patterns: ekstre, statement date / statement debt / card statement / e-mailed statement (the bare word 'statement' is also a generic collections term: 'debt statement'), customerNumber, "Freya Bank", currency lists (TRY/USD/EUR/GBP), e-posta / e-mail-statement wording.
# Dynamic patterns (when the files exist): every tool / endpoint name of case/*/ OpenAPI-like files and of mock/spec.freyabank.json that is NOT in the practice tools/openapi.json,
# and every string value (>= 6 chars) of the case's test customers (case/*/test-environment/test-customers.json).
cd "$(dirname "$0")/.." || exit 1
BASE=${1:-final-submit}
git rev-parse -q --verify "$BASE" > /dev/null || { echo "check_no_case_leak: base '$BASE' not found"; exit 2; }
.venv310/bin/python - "$BASE" <<'PY'
import json, re, subprocess, sys
from pathlib import Path
base = sys.argv[1]
diff = subprocess.run(["git", "diff", "-U0", base, "--", "builder", "scripts", ":(exclude)mock", ":(exclude)case", ":(exclude)traces", ":(exclude)out", ":(exclude)submission", ":(exclude)scripts/check_no_case_leak.sh"],
                      capture_output=True, text=True).stdout
pats = {"ekstre": r"ekstre", "statement (card/debt/date)": r"\bstatement[ _-]?(date|debt)\b|(card|account|e-?mail(ed)?) statement|statement[ _-]?(e-?mail|send)", "customerNumber": r"customer_?number", "Freya Bank": r"Freya Bank",
        "currency list": r"\b(TRY|TL)\b.{0,12}\b(USD|EUR|GBP)\b|\b(USD|EUR|GBP)\b.{0,12}\b(USD|EUR|GBP)\b", "e-posta/e-mail statement": r"e-?posta|e-?mail.{0,20}statement|statement.{0,20}e-?mail"}
dyn = {}
practice = set()
try:
    practice = {p.strip("/") for p in json.load(open("tools/openapi.json"))["paths"]}
except Exception:  # noqa: BLE001
    pass
def names_of(doc):
    out = set()
    if isinstance(doc, dict):
        for p, ops in (doc.get("paths") or {}).items():
            out.add(p.strip("/").split("/")[-1])
            for op in (ops or {}).values():
                if isinstance(op, dict) and op.get("operationId"):
                    out.add(op["operationId"])
    return out
cands = list(Path("case").glob("*/**/*.json")) + list(Path("case").glob("*/**/*.yaml")) + list(Path("mock").glob("spec.freyabank*.json"))
for f in cands:
    try:
        d = json.load(open(f))
    except Exception:  # noqa: BLE001
        continue
    if "test-customers" in f.name:
        def strs(o):
            if isinstance(o, dict):
                for v in o.values(): yield from strs(v)
            elif isinstance(o, list):
                for v in o: yield from strs(v)
            elif isinstance(o, str) and len(o) >= 6:
                yield o
        for s in strs(d):
            dyn["test customer value"] = dyn.get("test customer value", set()) | {re.escape(s)}
    else:
        d = d.get("openapi", d) if isinstance(d, dict) and isinstance(d.get("openapi"), dict) else d
        n = {x for x in names_of(d) if len(x) >= 4 and x not in practice}
        if n:
            dyn["case tool/endpoint name"] = dyn.get("case tool/endpoint name", set()) | {rf"\b{re.escape(x)}\b" for x in n}
allp = {k: re.compile(v, re.I) for k, v in pats.items()}
for k, vs in dyn.items():
    allp[k] = re.compile("|".join(sorted(vs)), re.I)
hits, cur, ln = [], None, 0
for line in diff.splitlines():
    if line.startswith("+++ b/"):
        cur = line[6:]
    elif line.startswith("@@"):
        m = re.search(r"\+(\d+)", line); ln = int(m.group(1)) - 1 if m else 0
    elif line.startswith("+") and not line.startswith("+++"):
        ln += 1
        for k, rx in allp.items():
            if rx.search(line[1:]):
                hits.append((cur, ln, k, line[1:].strip()[:100]))
                break
print(f"check_no_case_leak: base {base}; static patterns {len(pats)}, dynamic groups {sorted(dyn)}; added lines checked in builder/ scripts/; HITS {len(hits)}")
for h in hits[:20]:
    print(f"  {h[0]}:{h[1]} [{h[2]}] {h[3]}")
sys.exit(1 if hits else 0)
PY
