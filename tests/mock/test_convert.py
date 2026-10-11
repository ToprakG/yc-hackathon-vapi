import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("convert", REPO / "mock/convert.py")
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)


def test_csv_groups_products_per_customer(tmp_path):
    f = tmp_path / "c.csv"
    f.write_text("Customer ID,First Name,Last Name,DOB,Phone Last 4,Product Type,Past Due,Days Late\n"
                 "c1,A,B,1980-01-02,1234,credit_card,300,12\nc1,A,B,1980-01-02,1234,personal_loan,50.5,3\n")
    got = C.load_customers(f)
    assert len(got) == 1 and got[0]["customer_id"] == "c1" and len(got[0]["products"]) == 2
    assert got[0]["identity"] == {"date_of_birth": "1980-01-02", "phone_last4": "1234"}
    assert got[0]["products"][0]["days_late"] == 12 and got[0]["products"][1]["past_due"] == 50.5


def test_brief_a_spec_is_valid():
    assert C.check(json.loads((REPO / "mock/spec.brief-a.json").read_text())) == []


def test_check_reports_missing_identity_and_tool_paths():
    s = {"config": {"tools": {"nope": {}}, "identity": {"questions": ["x"]}, "outcome_map": {}, "account_fields": {}},
         "openapi": {"paths": {"/a": {}}}, "customers": [{"customer_id": "c", "identity": {}, "products": [{}]}]}
    bad = C.check(s)
    assert any("identity.x" in b for b in bad) and any("tool nope" in b for b in bad)
