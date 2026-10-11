#!/usr/bin/env python3
"""test-customers.json + endpoints.json (+ optional bank OpenAPI) -> table-mode spec for the Worker.

    python3 mock/final/build_table.py <test-customers.json> [-e mock/final/endpoints.json] [-o mock/final/table.freyabank.json] [--openapi bank.openapi.json]

One rule per customer / card / week from the pack, answered with exactly the listed status and body ('response' or 'yanit', 'http', 'gecikmeSaniye' = delay).
Section 6 changes only endpoints.json (method, path, aliases, which fields select the answer).
"""
import argparse, json, pathlib, re

ROLE_VALUE = {"customer": lambda c, card, week: c["customerNo"], "card": lambda c, card, week: card, "week": lambda c, card, week: week}


def leaf(x):
    return isinstance(x, dict) and "http" in x


def walk(svc_value, levels):
    """Yield (key tuple, leaf) for the nested {card: {week: leaf}} structure."""
    if leaf(svc_value):
        yield (), svc_value
    else:
        for k, v in svc_value.items():
            for rest, lf in walk(v, levels):
                yield (k,) + rest, lf


def out_of(lf):
    o = {"status": lf["http"], "body": lf.get("response", lf.get("yanit", {}))}
    if lf.get("gecikmeSaniye"):
        o["delay"] = lf["gecikmeSaniye"]
    return o


def build(data, ep):
    al = ep["aliases"]
    cond_key = lambda role: "|".join(al[role])
    eps, checks, writes = [], [], []
    unknown = None
    for c in data["customers"]:
        for name, v in c["services"].items():
            if leaf(v) and v["http"] == 404 and unknown is None and name == "cards.list":
                unknown = {"status": 404, "body": {**v["response"], "result": {**v["response"]["result"]}}}
    by_ep = {}
    for name, cfg in ep["services"].items():
        e = {"name": name, "method": cfg["method"], "path": cfg["path"], "rules": [],
             "default": cfg.get("default") or {"status": 404, "body": {"result": {"returnCode": "NOT_FOUND", "messageText": "No such record in the test environment.", "code": "NOT_FOUND", "message": "No such record in the test environment.", "type": "WARNING"}}}}
        by_ep[name] = (e, cfg)
        eps.append(e)
    for c in data["customers"]:
        cno = c["customerNo"]
        for name, v in c["services"].items():
            if name not in by_ep:
                continue
            e, cfg = by_ep[name]
            roles = cfg["by"]
            for keys, lf in walk(v, len(roles)):
                vals = {}
                ki = iter(keys)
                for r in roles:
                    vals[r] = cno if r == "customer" else next(ki)
                when = {cond_key(r): vals[r] for r in roles}
                out = out_of(lf)
                rule = {"key": cno, "when": when, **out}
                if cfg.get("record") and out["status"] < 400:
                    rule["record"] = {"kind": cfg["record"], "data": {"customerNo": cno, **{r: vals[r] for r in roles if r != "customer"}}}
                e["rules"].append(rule)
                req = {al[r][0]: vals[r] for r in roles if not al[r][0].startswith("header.")}
                check = {"name": f"{cno} {name} {'/'.join(map(str, keys))}".strip(), "request": {"method": cfg["method"], "path": cfg["path"]}, "expect": {"status": out["status"], "body": out["body"]}}
                hdr = {al[r][0][7:]: vals[r] for r in roles if al[r][0].startswith("header.")}
                check["request"]["body" if cfg["method"] != "GET" else "query"] = req
                if hdr:
                    check["request"]["headers"] = hdr
                if "{" in cfg["path"]:   # path params: fill {name} from the matching role
                    p = cfg["path"]
                    for m in re.findall(r"\{(\w+)\}", p):
                        role = next((r for r in roles if m in al[r]), None)
                        if role:
                            p = p.replace("{" + m + "}", str(vals[role]))
                            check["request"].get("body", check["request"].get("query", {})).pop(m, None)
                    check["request"]["path"] = p
                checks.append(check)
                if rule.get("record"):
                    writes.append({"kind": cfg["record"], "data": rule["record"]["data"]})
    # a card is also found by its last four digits when those are unique among all cards
    return {"mode": "table", "id": ep.get("tenant", "freyabank"), "info": {"title": "Freya Bank statement services (test environment)", "version": "1"},
            "base_path": ep.get("base_path", ""), "ledger_key": al["customer"], "max_delay": 25, "endpoints": eps, "checks": checks, "checks_parallel": 8,
            "expect_writes": writes[:3]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("customers"); ap.add_argument("-e", default=str(pathlib.Path(__file__).with_name("endpoints.json")))
    ap.add_argument("-o", default=str(pathlib.Path(__file__).with_name("table.freyabank.json"))); ap.add_argument("--openapi")
    a = ap.parse_args()
    ep = json.load(open(a.e))
    spec = build(json.load(open(a.customers)), ep)
    oa = a.openapi or ep.get("openapi_file")
    if oa:
        spec["openapi"] = json.load(open(oa))
    json.dump(spec, open(a.o, "w"), ensure_ascii=False)
    n = sum(len(e["rules"]) for e in spec["endpoints"])
    print(f"{a.o}: {len(spec['endpoints'])} endpoints, {n} rules, {len(spec['checks'])} checks, {len(spec['expect_writes'])} write checks")
