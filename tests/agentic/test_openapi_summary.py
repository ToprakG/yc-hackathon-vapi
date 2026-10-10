import json

import pytest

from builder.agentic.tools import openapi_summary as oa
from tests.agentic.conftest import FAKES, REPO


def test_kit_api_has_the_seven_tools(kit_api):
    assert list(kit_api["tools"]) == list(oa.KIT_TOOLS) and not kit_api["missing_kit_tools"]
    assert kit_api["base_url"] == "https://freya-bank-mock.freyavoice.workers.dev/v1"
    vi = kit_api["tools"]["verify_identity"]
    assert vi["url"].endswith("/v1/verify_identity") and vi["method"] == "POST"
    assert vi["request"]["field"]["enum"] == ["date_of_birth", "phone_last4"] and vi["request"]["field"]["required"]
    products = kit_api["tools"]["get_account"]["response"]["products"]["items"]
    assert "type" in products and products["type"]["enum"] == ["credit_card", "personal_loan", "car_loan"]
    assert "500" in vi["statuses"]


@pytest.mark.parametrize("path", FAKES, ids=lambda p: p.parent.name)
def test_every_fake_api_parses(path):
    s = oa.load(path)
    assert set(s["tools"]) == set(oa.KIT_TOOLS)
    assert s["base_url"].startswith("https://") and all(t["url"].startswith(s["base_url"]) for t in s["tools"].values())
    assert len(oa.render(s)) < 14000


def _api(name):
    return oa.load(REPO / "testbed" / "fake_briefs" / name / "tools.openapi.json")["tools"]


def test_variations_are_visible():
    kestrel = _api("f3-kestrel")
    assert kestrel["create_promise"]["request"]["amount_cents"]["type"] == "integer"  # cents
    assert "account_ref" in kestrel["create_promise"]["request"]  # renamed product id
    assert set(_api("f5-halden-email")["schedule_callback"]["request"]) == {"customer_id", "callback_at"}  # datetime
    lumen = _api("f7-lumen-codes")["close_call"]["request"]
    assert set(lumen) == {"customer_id", "code"} and "10-PTP" in lumen["code"]["enum"]  # code mode
    assert set(_api("f4-brightwell")["verify_identity"]["request"]) == {"customer_id", "check", "value"}


def test_local_refs_are_resolved():
    spec = {"openapi": "3.0.0", "servers": [{"url": "https://x.example/v1/"}],
            "components": {"schemas": {"Req": {"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}}}},
            "paths": {"/t": {"post": {"requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Req"}}}}}}}}
    s = oa.summarize(json.loads(json.dumps(spec)))
    assert s["tools"]["t"]["url"] == "https://x.example/v1/t" and s["tools"]["t"]["request"]["a"] == {"type": "integer", "required": True}
