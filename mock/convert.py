"""Team tooling: test customers (xlsx/csv/md/docx/pdf/json) + service contract (md/docx/pdf/json openapi) -> mock/spec.<id>.json (see mock/SPEC.md).

    python3 mock/convert.py --id brief-a --name "Freya Bank" --contract briefs/brief-a.md --openapi tools/openapi.json \
        --customers public-test-set.json --config-from seed:A                     # offline, no LLM
    python3 mock/convert.py --id x --contract contract.pdf --customers accounts.xlsx             # LLM-assisted (claude CLI): config from the contract, customers from messy files
    python3 mock/convert.py --check mock/spec.brief-a.json

--config-from: a config.json path, `seed:A` / `seed:B` (Brief A/B canonical config), or omitted (the LLM reads the contract and the openapi).
Customers: .json (public-test-set / cases list / spec customers), .csv/.xlsx with recognisable headers (offline), anything else -> LLM."""
import argparse
import csv
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "vendor/build-the-builder"))

HEAD = {"first_name": "first_name", "firstname": "first_name", "first": "first_name", "given_name": "first_name",
        "last_name": "last_name", "lastname": "last_name", "surname": "last_name", "family_name": "last_name",
        "title": "title", "salutation": "title",
        "date_of_birth": "date_of_birth", "dob": "date_of_birth", "birth_date": "date_of_birth", "birthdate": "date_of_birth",
        "phone_last4": "phone_last4", "phone_last_4": "phone_last4", "last4": "phone_last4", "phone_last_four": "phone_last4",
        "customer_id": "customer_id", "id": "customer_id", "customer": "customer_id", "now": "now"}
PRODUCT_NUM = {"past_due", "days_late", "minimum_payment", "instalment_amount", "min_due", "balance", "overdue_amount"}
SKIP_PRODUCT = {"type", "product_type"}


def read_text(path: Path) -> str:
    s = path.suffix.lower()
    if s in (".md", ".txt", ".json", ".csv", ".yaml", ".yml"):
        return path.read_text(errors="replace")
    if s == ".docx":
        import docx
        d = docx.Document(str(path))
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            parts += [" | ".join(c.text for c in r.cells) for r in t.rows]
        return "\n".join(parts)
    if s == ".pdf":
        import pypdf
        return "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(str(path)).pages)
    if s in (".xlsx", ".xlsm"):
        return "\n".join(" | ".join("" if c is None else str(c) for c in row) for row in _xlsx_rows(path))
    raise SystemExit(f"unsupported file type {path}")


def _xlsx_rows(path: Path):
    import openpyxl
    ws = openpyxl.load_workbook(str(path), data_only=True).active
    return [list(r) for r in ws.iter_rows(values_only=True) if any(c not in (None, "") for c in r)]


def llm(system: str, user: str, max_tokens=8000) -> str:
    from builder.template_cc import llm as L
    L.load_env()
    return L._claude_cli(system, user, "sonnet", max_tokens, 600)[0]


def json_out(text: str):
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    s = m.group(1) if m else text
    i = min([x for x in (s.find("{"), s.find("[")) if x >= 0] or [0])
    return json.loads(s[i:])


def cid(v: dict) -> str:
    key = "|".join(str(v.get(k, "")) for k in ("first_name", "last_name")) + str(v.get("_k", ""))
    return "c_" + hashlib.sha1(key.encode()).hexdigest()[:8]


def norm_customer(c: dict, i: int) -> dict:
    vars_ = dict(c.get("variables") or {})
    for k in ("first_name", "last_name", "title", "now"):
        if k in c and k not in vars_:
            vars_[k] = c[k]
    out = {"customer_id": c.get("customer_id") or cid({**vars_, "_k": i}), "variables": vars_,
           "identity": dict(c.get("identity") or {}), "products": [dict(p) for p in c.get("products") or []]}
    return out


def customers_from_table(rows: list) -> list | None:
    if not rows or len(rows) < 2:
        return None
    heads = [re.sub(r"[^a-z0-9]+", "_", str(h or "").strip().lower()).strip("_") for h in rows[0]]
    mapped = [HEAD.get(h) for h in heads]
    if not {"first_name", "last_name"} <= set(mapped) and "customer_id" not in mapped:
        return None
    groups, order = {}, []
    for r in rows[1:]:
        rec = dict(zip(heads, r))
        key = next((str(rec[h]) for h in heads if HEAD.get(h) == "customer_id" and rec.get(h) not in (None, "")), None) \
            or (str(rec.get(next(h for h in heads if HEAD.get(h) == "first_name"))) + " " + str(rec.get(next(h for h in heads if HEAD.get(h) == "last_name"))))
        if key not in groups:
            groups[key] = {"variables": {}, "identity": {}, "products": []}
            order.append(key)
        g = groups[key]
        prod = {}
        for h, m in zip(heads, mapped):
            v = rec.get(h)
            if v in (None, ""):
                continue
            if isinstance(v, str):
                v = v.strip()
            if m in ("first_name", "last_name", "title", "now"):
                g["variables"][m] = str(v)
            elif m in ("date_of_birth", "phone_last4"):
                g["identity"][m] = (v.strftime("%Y-%m-%d") if hasattr(v, "strftime") else str(v))
            elif m == "customer_id":
                g["customer_id"] = str(v)
            elif h in SKIP_PRODUCT:
                prod["type"] = str(v)
            elif isinstance(v, (int, float)) or re.fullmatch(r"-?\d+(\.\d+)?", str(v)):
                f = float(v)
                prod[h] = int(f) if f.is_integer() and h not in PRODUCT_NUM - {"days_late"} else f   # amounts stay floats, counts are ints
                if h.endswith(("last4", "last_4")):
                    prod[h] = str(v)
            else:
                prod[h] = str(v)
        if prod:
            g["products"].append(prod)
    return [norm_customer(groups[k], i) for i, k in enumerate(order)]


LLM_CUSTOMERS = """Convert the test-customer data into JSON: a list of customers, each
{"variables": {"first_name","last_name","title","now"}, "identity": {<one key per security question, e.g. "date_of_birth" as YYYY-MM-DD, "phone_last4">},
 "products": [{"type": <as in the data>, "past_due": number, "days_late": number, <every other numeric field of the product with the data's own name>}]}.
Keep the data's own field names and values; do not invent customers or fields. Output ONLY the JSON list."""


def load_customers(path: Path, only_brief: str = "") -> list:
    s = path.suffix.lower()
    if s == ".json":
        d = json.loads(path.read_text())
        d = d.get("customers", d) if isinstance(d, dict) else d
        seen, out = set(), []
        for i, c in enumerate(x for x in d if not only_brief or x.get("brief") == only_brief):
            nc = norm_customer(c, i)
            sig = json.dumps([nc["variables"].get("first_name"), nc["variables"].get("last_name"), nc["identity"]], sort_keys=True)
            if sig in seen:
                continue   # a case list repeats customers: one account each
            seen.add(sig)
            out.append(nc)
        return out
    rows = None
    if s == ".csv":
        rows = list(csv.reader(path.open(newline="")))
    elif s in (".xlsx", ".xlsm"):
        rows = _xlsx_rows(path)
    got = customers_from_table(rows) if rows else None
    if got:
        return got
    return [norm_customer(c, i) for i, c in enumerate(json_out(llm(LLM_CUSTOMERS, read_text(path))))]


LLM_CONFIG = """You read a bank's service contract (the call-handling brief and API description) and output the CANONICAL mock-bank config as JSON.
Follow EXACTLY the shape of this example (keys, nesting, value types); take every value from the contract, never invent. Use the API's own field names in "tools".
Example:
%s
Output ONLY the JSON object."""


def load_config(arg: str | None, contract: str, openapi: dict) -> dict:
    if arg and arg.startswith("seed:"):
        from seed import policy_ab
        return dict({"A": policy_ab.POLICY_A, "B": policy_ab.POLICY_B}[arg[5:]])
    if arg:
        return json.loads(Path(arg).read_text())
    ex = json.loads((REPO / "testbed/fake_briefs/f5-halden-email/config.json").read_text())
    return json_out(llm(LLM_CONFIG % json.dumps(ex, indent=1), "CONTRACT:\n" + contract + "\n\nOPENAPI:\n" + json.dumps(openapi)[:30000]))


def check(spec: dict) -> list:
    bad = []
    cfg = spec.get("config") or {}
    for k in ("tools", "identity", "outcome_map", "account_fields"):
        if k not in cfg:
            bad.append(f"config.{k} missing")
    qs = (cfg.get("identity") or {}).get("questions") or []
    for c in spec.get("customers") or []:
        for q in qs:
            if q not in c.get("identity", {}):
                bad.append(f"{c['customer_id']}: identity.{q} missing")
        if not c.get("products"):
            bad.append(f"{c['customer_id']}: no products")
    paths = set((spec.get("openapi") or {}).get("paths") or {})
    for t in (cfg.get("tools") or {}):
        if paths and not any(p.rstrip("/").endswith("/" + t) or p.strip("/") == t for p in paths):
            bad.append(f"tool {t}: no matching openapi path")
    ids = [c["customer_id"] for c in spec.get("customers") or []]
    if len(ids) != len(set(ids)):
        bad.append("duplicate customer_id")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id"); ap.add_argument("--name", default="")
    ap.add_argument("--contract"); ap.add_argument("--openapi"); ap.add_argument("--customers")
    ap.add_argument("--only-brief", default="", help="json case lists: keep the cases of this brief key (A/B)"); ap.add_argument("--config-from"); ap.add_argument("--out"); ap.add_argument("--check")
    a = ap.parse_args()
    if a.check:
        bad = check(json.loads(Path(a.check).read_text()))
        print("OK" if not bad else "\n".join(bad)); return 1 if bad else 0
    openapi = json.loads(Path(a.openapi).read_text()) if a.openapi else {}
    contract = read_text(Path(a.contract)) if a.contract else ""
    spec = {"spec_version": 1, "id": a.id, "name": a.name or a.id, "config": load_config(a.config_from, contract, openapi),
            "openapi": openapi, "customers": load_customers(Path(a.customers), a.only_brief)}
    out = Path(a.out or REPO / "mock" / f"spec.{a.id}.json")
    out.write_text(json.dumps(spec, indent=1, ensure_ascii=False))
    bad = check(spec)
    print(f"wrote {out}: {len(spec['customers'])} customers; " + ("OK" if not bad else "PROBLEMS:\n  " + "\n  ".join(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
