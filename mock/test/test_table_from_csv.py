import csv, io, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from table_from_csv import build


def rows(text):
    return list(csv.DictReader(io.StringIO(text)))


def test_rows_become_ordered_rules_and_unknown_endpoint_fails():
    skel = {"mode": "table", "endpoints": [{"name": "look", "method": "GET", "path": "/a/{id}"}]}
    out = build(skel, rows("endpoint,when.id,status,body.balance,body.cur.code,record_kind\nlook,A1,200,12.5,EUR,seen\nGET /a/{id},*,404,,,\n"))
    r = out["endpoints"][0]["rules"]
    assert r[0] == {"when": {"id": "A1"}, "status": 200, "body": {"balance": 12.5, "cur": {"code": "EUR"}}, "record": {"kind": "seen"}}
    assert r[1]["when"] == {"id": {"$exists": True}} and r[1]["status"] == 404
    try:
        build(skel, rows("endpoint,status\nnope,200\n")); assert False
    except SystemExit as e:
        assert "unknown endpoint" in str(e)
