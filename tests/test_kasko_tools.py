import json

import pytest
from fastapi.testclient import TestClient

from agentforge.domain import load_domain
from agentforge.domain.kasko import tools_server
from agentforge.domain.kasko.tools_server import app

POLICY = "KSK-2024-004512"
GOOD_ID = {"tckn_last4": "8904", "birth_date": "1985-03-14"}
CLAIM = {
    "policy_number": POLICY,
    "date": "2026-10-08",
    "location": "İstanbul Kadıköy Bağdat Caddesi",
    "description": "Arkadan çarpıldı.",
    "injury": False,
    "other_plate": "34 XYZ 99",
}


@pytest.fixture()
def client():
    tools_server.reset_state()
    return TestClient(app)


def vapi_body(name, args, call_id="call-1", session="sess-vapi"):
    return {
        "message": {
            "type": "tool-calls",
            "call": {"id": session},
            "toolCallList": [{"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}],
        }
    }


def test_tools_json_loads():
    task_md, tools = load_domain("kasko")
    assert "kimlik" in task_md.lower()
    assert [t.name for t in tools] == ["verify_identity", "get_policy", "create_claim", "transfer_to_human"]
    assert all(t.preconditions for t in tools)
    claim = next(t for t in tools if t.name == "create_claim")
    assert {f.name for f in claim.extraction_schema} == {"date", "location", "injury", "other_plate"}


def test_preconditions_enforced(client):
    out = client.post("/tools/get_policy?session_id=s1", json={"policy_number": POLICY}).json()
    assert "error" in out
    out = client.post("/tools/create_claim?session_id=s1", json=CLAIM).json()
    assert "error" in out
    bad = client.post("/tools/verify_identity?session_id=s1", json={"tckn_last4": "0000", "birth_date": "1985-03-14"}).json()
    assert bad["verified"] is False
    # Verification in another session does not unlock this one.
    client.post("/tools/verify_identity?session_id=s2", json=GOOD_ID)
    assert "error" in client.post("/tools/get_policy?session_id=s1", json={"policy_number": POLICY}).json()
    # Verified person cannot read someone else's policy.
    assert "error" in client.post("/tools/get_policy?session_id=s2", json={"policy_number": "KSK-2024-007831"}).json()


def test_successful_claim_plain_json(client):
    ok = client.post("/tools/verify_identity", headers={"X-Session-Id": "s3"}, json={"tckn_last4": "8904", "birth_date": "14.03.1985"}).json()
    assert ok["verified"] is True and ok["policy_number"] == POLICY
    policy = client.post("/tools/get_policy", headers={"X-Session-Id": "s3"}, json={"policy_number": "ksk-2024-004512"}).json()
    assert "deprem" in policy["exclusions"]
    claim = client.post("/tools/create_claim", headers={"X-Session-Id": "s3"}, json=CLAIM).json()
    assert claim["created"] is True and claim["claim_id"].startswith("HSR-")
    log = client.get("/calls/s3").json()
    assert [c["name"] for c in log] == ["verify_identity", "get_policy", "create_claim"]
    assert set(log[0]) == {"session_id", "name", "args", "result", "timestamp"}


def test_successful_claim_vapi_webhook(client):
    out = client.post("/tools/verify_identity", json=vapi_body("verify_identity", GOOD_ID, "c1")).json()
    assert out["results"][0]["toolCallId"] == "c1"
    assert json.loads(out["results"][0]["result"])["verified"] is True
    out = client.post("/tools/create_claim", json=vapi_body("create_claim", json.dumps(CLAIM), "c2")).json()
    result = json.loads(out["results"][0]["result"])
    assert result["created"] is True and result["other_plate"] == "34 XYZ 99"
    assert len(client.get("/calls/sess-vapi").json()) == 2


def test_reset_clears_log(client):
    client.post("/tools/transfer_to_human?session_id=s4", json={"reason": "yaralanma"})
    assert client.get("/calls/s4").json()
    client.post("/reset")
    assert client.get("/calls/s4").json() == []
