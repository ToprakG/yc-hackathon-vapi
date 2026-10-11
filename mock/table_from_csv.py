#!/usr/bin/env python3
"""Fill a table-mode skeleton with rules from a CSV (one row = one rule).

    python3 mock/table_from_csv.py <skeleton.json> <rules.csv> [-o spec.json]

CSV columns: `endpoint` (the endpoint `name`, or "METHOD /path"), `when.<field>` (exact match; empty cell = no condition; `*` = field must exist;
`!` = field must be absent), `status` (default 200), `body.<dotted.path>` (response value; numbers/true/false/null are typed; `{{field}}` templates allowed),
`record_kind` (optional: record a write of this kind with the request inputs). Rows keep their order: first matching rule wins.
"""
import argparse, csv, json, sys


def typed(v):
    if v is None:
        return None
    s = v.strip()
    if s in ("true", "false", "null"):
        return json.loads(s)
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return v


def build(skel, rows):
    eps = {}
    for e in skel["endpoints"]:
        eps[e.get("name") or f'{e.get("method", "GET")} {e["path"]}'] = e
        eps[f'{e.get("method", "GET").upper()} {e["path"]}'] = e
    for n, row in enumerate(rows, 2):
        key = (row.get("endpoint") or "").strip()
        if key not in eps:
            raise SystemExit(f"row {n}: unknown endpoint {key!r}")
        rule = {"when": {}, "status": int(row.get("status") or 200), "body": {}}
        for col, val in row.items():
            if val is None or val == "" or col is None:
                continue
            if col.startswith("when."):
                rule["when"][col[5:]] = {"$exists": True} if val == "*" else {"$exists": False} if val == "!" else typed(val)
            elif col.startswith("body."):
                cur = rule["body"]
                *head, last = col[5:].split(".")
                for h in head:
                    cur = cur.setdefault(h, {})
                cur[last] = typed(val)
        if row.get("record_kind"):
            rule["record"] = {"kind": row["record_kind"].strip()}
        eps[key].setdefault("rules", []).append(rule)
    return skel


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("skeleton"); ap.add_argument("csv"); ap.add_argument("-o")
    a = ap.parse_args()
    out = build(json.load(open(a.skeleton)), list(csv.DictReader(open(a.csv, newline="", encoding="utf-8-sig"))))
    (open(a.o, "w") if a.o else sys.stdout).write(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
