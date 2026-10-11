#!/usr/bin/env python3
"""test-customers.json + endpoints.json (+ bank OpenAPI) -> table-mode spec for the Worker.

    python3 mock/final/build_table.py <test-customers.json> [-e mock/final/endpoints.json] [-o mock/final/table.freyabank.json] [--openapi bank.openapi.json]

One rule per customer / card / week from the pack, answered with exactly the listed status and body ('response'/'yanit', 'http', 'delaySeconds' etc. = delay_seconds).
Not in the file -> the contract's 404/400 for that service (section 6). Missing required field -> 400 INVALID_ARGUMENTS_ERROR. Token endpoint per section 2.
"""
import argparse, json, pathlib

HERE = pathlib.Path(__file__).resolve().parent


def leaf(x):
    return isinstance(x, dict) and "http" in x


def walk(v):
    if leaf(v):
        yield (), v
    else:
        for k, sub in v.items():
            for rest, lf in walk(sub):
                yield (k,) + rest, lf


def out_of(lf):
    o = {"status": lf["http"], "body": lf.get("response", lf.get("yanit", {}))}
    d = lf.get("gecikmeSaniye", lf.get("delaySeconds", lf.get("delay_seconds")))
    if d:
        o["delay_seconds"] = d
    return o


def err(status, code, typ, msg):
    return {"status": status, "body": {"result": {"guid": "{{guid}}", "returnCode": code, "messageText": msg, "code": code, "message": msg, "type": typ,
                                                  "details": {"guid": "{{guid}}", "rootCause": "TechnicalError" if status == 500 else "NotFoundException" if status == 404 else "IllegalArgumentException", "errorOrigin": "ivr-gateway-test:ivr-channel-v0"}}}}


def build(data, ep, openapi=None):
    al = ep["aliases"]
    key = lambda role: al[role][0]
    eps, checks, writes = [], [], []
    by_ep = {}
    for name, cfg in ep["services"].items():
        un = cfg["unknown"]
        e = {"name": name, "method": "POST", "path": cfg["path"], "rules": [], "default": err(*un),
             "required": [{"any": f, "out": err(400, "INVALID_ARGUMENTS_ERROR", "ERROR", msg)} for f, msg in cfg.get("required", [])]}
        by_ep[name] = (e, cfg); eps.append(e)
    for c in data["customers"]:
        cno = c["customerNo"]
        for name, v in c["services"].items():
            if name not in by_ep:
                continue
            e, cfg = by_ep[name]
            roles = cfg["by"]
            for keys, lf in walk(v):
                it = iter(keys)
                vals = {r: (cno if r == "customer" else next(it)) for r in roles}
                out = out_of(lf)
                rule = {"key": cno, "when": {key(r): vals[r] for r in roles}, **out}
                if cfg.get("record") and out["status"] < 400:
                    tmpl = json.loads(json.dumps(cfg["record_data"]).replace('"@customer"', json.dumps(cno)))
                    rule["record"] = {"kind": cfg["record"], "data": tmpl}
                e["rules"].append(rule)
                reqdata = {key(r): vals[r] for r in roles}
                reqdata.update({k: x for k, x in cfg.get("extra", {}).items() if k not in reqdata})
                checks.append({"name": f"{cno} {name} {'/'.join(map(str, keys))}".strip(),
                               "request": {"method": "POST", "path": cfg["path"], "body": {"data": reqdata, "call": {"ani": "+905550000000", "lang": "tr"}}},
                               "expect": {"status": out["status"], "body": out["body"]}})
                if rule.get("record"):
                    w = json.loads(json.dumps(rule["record"]["data"]))
                    for k, x in list(w.items()):
                        if isinstance(x, str) and x.startswith("{{"):
                            w[k] = reqdata.get(x[2:-2])
                    writes.append({"kind": cfg["record"], "data": w})
    tok = ep["token"]
    eps.append({"name": "oauth2.token", "method": "POST", "path": tok["path"], "absolute": True,
                "rules": [{"status": 200, "body": {"access_token": tok["access_token"], "token_type": "Bearer", "expires_in": tok["expires_in"]}}]})
    checks.append({"name": "token", "request": {"method": "POST", "path": tok["path"], "absolute": True, "body": {}}, "expect": {"status": 200, "body": {"token_type": "Bearer", "expires_in": tok["expires_in"]}}})
    # section 6 / 4: unknown customer, unknown card, empty field
    checks += [
        {"name": "template variable -> sample record", "request": {"method": "POST", "path": "/cards.list", "body": {"data": {"customerNo": "{{customerNumber}}"}}}, "expect": {"status": 200, "body": {"data": {"exitState": "1_CARD"}}}},
        {"name": "unknown customer -> 404 102", "request": {"method": "POST", "path": "/cards.list", "body": {"data": {"customerNo": "00000000", "aiFlow": "CardOps"}}}, "expect": {"status": 404, "body": {"result": {"code": "FB_IVR_CHANNEL_102", "type": "WARNING"}}}},
        {"name": "unknown card -> 404 120", "request": {"method": "POST", "path": "/cards.balance", "body": {"data": {"cardNumber": "999999******9999"}}}, "expect": {"status": 404, "body": {"result": {"code": "FB_IVR_CHANNEL_120"}}}},
        {"name": "empty card -> 400", "request": {"method": "POST", "path": "/cards.balance", "body": {"data": {"cardNumber": ""}}}, "expect": {"status": 400, "body": {"result": {"code": "INVALID_ARGUMENTS_ERROR", "message": "card number cannot be empty"}}}},
        {"name": "no data -> 400", "request": {"method": "POST", "path": "/cards.list", "body": {}}, "expect": {"status": 400}},
    ]
    spec = {"mode": "table", "id": ep.get("tenant", "freyabank"), "info": {"title": "Freya Bank voice statement services", "version": "1"},
            "base_path": ep["base_path"], "ledger_key": [key("customer")], "max_delay": 25, "endpoints": eps, "checks": checks, "checks_parallel": 8, "placeholders": ep.get("placeholders", {}), "expect_writes": writes[:3]}
    if openapi:
        spec["openapi"] = openapi
    return spec


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("customers"); ap.add_argument("-e", default=str(HERE / "endpoints.json"))
    ap.add_argument("-o", default=str(HERE / "table.freyabank.json")); ap.add_argument("--openapi")
    a = ap.parse_args()
    ep = json.load(open(a.e))
    oa = a.openapi or ep.get("openapi_file")
    oa = json.load(open(oa if pathlib.Path(oa).exists() else HERE.parent.parent / oa)) if oa else None
    spec = build(json.load(open(a.customers)), ep, oa)
    json.dump(spec, open(a.o, "w"), ensure_ascii=False)
    print(f"{a.o}: {len(spec['endpoints'])} endpoints, {sum(len(e['rules']) for e in spec['endpoints'])} rules, {len(spec['checks'])} checks, openapi={'yes' if oa else 'no'}")
