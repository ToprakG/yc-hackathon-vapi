import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def test_ingest_order_headers_and_api_fallback(tmp_path, monkeypatch):
    import docx, openpyxl
    from builder import ingest as I
    c = tmp_path / "case"; c.mkdir()
    (c / "BRIEF.md").write_text("ana kural şğü"); (c / "README.md").write_text("readme")
    (c / "aaa_sss.md").write_text("soru cevap")
    d = docx.Document(); d.add_paragraph("duyuru metni"); t = d.add_table(rows=1, cols=2); t.rows[0].cells[0].text = "a"; t.rows[0].cells[1].text = "b"; d.save(str(c / "duyuru.docx"))
    wb = openpyxl.Workbook(); wb.active.append(["x", "y"]); wb.active.append([1, 2]); wb.save(str(c / "t.xlsx"))
    (c / "spec.json").write_text(json.dumps({"openapi": "3.0.0", "paths": {"/a": {}}, "servers": [{"url": "https://real.example/v1"}]}))
    monkeypatch.setattr(I, "fetch_openapi", lambda u: (_ for _ in ()).throw(OSError("down")))
    r = I.ingest(c, "http://mock.example", tmp_path / "out")
    text = Path(r["brief"]).read_text()
    heads = [l for l in text.splitlines() if l.startswith("=== FILE:")]
    assert heads[:2] == ["=== FILE: BRIEF.md ===", "=== FILE: README.md ==="] and len(heads) == 5
    assert "duyuru metni" in text and "| x | y |" in text and "ana kural şğü" in text and "spec.json" not in text
    assert json.loads(Path(r["api"]).read_text())["servers"][0]["url"] == "https://real.example/v1"


def test_dated_files_come_oldest_to_newest_after_the_first_two(tmp_path, monkeypatch):
    from builder import ingest as I
    c = tmp_path / "case"; (c / "sources").mkdir(parents=True)
    (c / "BRIEF.md").write_text("b"); (c / "README.md").write_text("r"); (c / "example.md").write_text("undated")
    (c / "sources" / "2026-10-09-late.md").write_text("late"); (c / "sources" / "2026-09-02-early.md").write_text("early")
    (c / "spec.json").write_text(json.dumps({"openapi": "3.0.0", "paths": {"/a": {}}}))
    monkeypatch.setattr(I, "fetch_openapi", lambda u: None)
    text = Path(I.ingest(c, "", tmp_path / "o")["brief"]).read_text()
    heads = [l for l in text.splitlines() if l.startswith("=== FILE:")]
    assert [h.split(": ")[1].split(" ===")[0] for h in heads] == ["BRIEF.md", "README.md", "example.md", "sources/2026-09-02-early.md", "sources/2026-10-09-late.md"]
    assert text.startswith("NOTE:") and "later-dated document overrides" in text


def test_a_huge_data_file_keeps_its_shape_and_first_records_only():
    from builder import ingest as I
    big = json.dumps({"customers": [{"id": str(i), "name": "N" + str(i), "cards": [{"x": i}]} for i in range(5000)]})
    out = I.shrink("test-environment/test-customers.json", big)
    assert len(out) < 20000 and "LARGE DATA FILE" in out and "5000 items" in out and "omitted" in out
    assert I.shrink("a.md", "short") == "short"


def test_a_converted_document_is_cached_by_content_hash(tmp_path, monkeypatch):
    import docx
    from builder import ingest as I
    monkeypatch.setattr(I, "_CACHE", tmp_path / "cache")
    f = tmp_path / "d.docx"
    d = docx.Document(); d.add_paragraph("merhaba dünya"); d.save(str(f))
    assert "merhaba" in I._cached_text(f)
    monkeypatch.setattr(I, "read_docx", lambda p: (_ for _ in ()).throw(AssertionError("converted again")))
    assert "merhaba" in I._cached_text(f)
