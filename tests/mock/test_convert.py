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


def _turkish_xlsx(path, spec):
    import datetime
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Müşteri No", "Ad", "Soyad", "Hitap", "Doğum Tarihi", "Telefon Son 4 Hane", "Arama Zamanı", "Ürün", "Kart Son Dört", "Ekstre Borcu",
               "Gecikme Gün", "Asgari Ödeme", "Taksit Tutarı"])

    def tl(x):
        s = f"{x:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
        return s + " TL"
    months = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
    for n, c in enumerate(spec["customers"]):
        dob = datetime.date.fromisoformat(c["identity"]["date_of_birth"])
        dtxt = [dob.strftime("%d.%m.%Y"), f"{dob.day} {months[dob.month - 1]} {dob.year}", datetime.datetime(dob.year, dob.month, dob.day)][n % 3]
        now = datetime.datetime.fromisoformat(c["variables"]["now"])
        for p in c["products"]:
            ws.append([c["customer_id"], c["variables"]["first_name"], c["variables"]["last_name"], c["variables"]["title"], dtxt,
                       int(c["identity"]["phone_last4"]), now.strftime("%d.%m.%Y %H:%M"), p["type"], int(p["card_last4"]) if p.get("card_last4") else None,
                       tl(p["past_due"]), str(p["days_late"]), tl(p["minimum_payment"]) if p.get("minimum_payment") else None,
                       tl(p["instalment_amount"]) if p.get("instalment_amount") else None])
    wb.save(path)


def test_turkish_xlsx_round_trips_to_the_same_values(tmp_path):
    spec = json.loads((REPO / "mock/spec.brief-a.json").read_text())
    f = tmp_path / "musteriler.xlsx"
    _turkish_xlsx(f, spec)
    got = C.load_customers(f)
    want = spec["customers"]
    assert len(got) == len(want)
    for g, w in zip(got, want):
        assert g["customer_id"] == w["customer_id"] and g["identity"] == w["identity"], (g, w)
        assert g["variables"] == w["variables"]
        for gp, wp in zip(g["products"], w["products"]):
            assert {k: v for k, v in gp.items() if k in wp} == wp, (gp, wp)
    spec2 = dict(spec, customers=got)
    assert C.check(spec2) == []


def test_turkish_formats():
    assert C.parse_amount("1.234,56 TL") == 1234.56 and C.parse_amount("₺ 12.000") == 12000.0 and C.parse_amount("99,5") == 99.5
    assert C.parse_amount("1,234.56") == 1234.56 and C.parse_amount(310.25) == 310.25
    assert C.parse_date("14.03.1988") == C.parse_date("14 Mart 1988") == C.parse_date("1988-03-14") == "1988-03-14"
    assert C.parse_date("3 Şubat 1990") == "1990-02-03" and C.parse_date("5 Ağustos 1975") == "1975-08-05"
    assert C.parse_now("14.10.2026 11:00") == "2026-10-14T11:00"


def test_missing_required_columns_fail_loudly(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "llm", lambda *a, **k: "{}")
    f = tmp_path / "x.csv"
    f.write_text("Ad,Soyad,Renk\nA,B,mavi\n")
    try:
        C.load_customers(f)
    except SystemExit as e:
        assert "FAILED" in str(e)
    else:
        raise AssertionError("must fail loudly")
