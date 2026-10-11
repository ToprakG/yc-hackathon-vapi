"""freya_retry: 5xx retry on GET/PUT only (3 tries), and the outage signature. No network."""

import types

import pytest

from builder.template_cc import freya_retry


def fake_module(fails, status="503"):
    calls = []

    def api(method, path, body=None, **params):
        calls.append(method)
        if len(calls) <= fails:
            raise RuntimeError(f"{method} {path} -> {status}: error code: {status}")
        return {"ok": True}
    m = types.SimpleNamespace(api=api)
    return m, calls


def test_get_is_retried_up_to_three_tries():
    m, calls = fake_module(2)
    pauses = []
    freya_retry.install(m, sleep=pauses.append)
    assert m.api("GET", "/x") == {"ok": True} and len(calls) == 3 and pauses == [10, 10]


def test_gives_up_after_three_tries_and_never_retries_post_or_4xx():
    m, calls = fake_module(5)
    freya_retry.install(m, sleep=lambda s: None)
    with pytest.raises(RuntimeError):
        m.api("PUT", "/x", {})
    assert len(calls) == 3
    m, calls = fake_module(5)
    freya_retry.install(m, sleep=lambda s: None)
    with pytest.raises(RuntimeError):
        m.api("POST", "/api/v2/simulations", {})
    assert len(calls) == 1
    m, calls = fake_module(5, status="404")
    freya_retry.install(m, sleep=lambda s: None)
    with pytest.raises(RuntimeError):
        m.api("GET", "/x")
    assert len(calls) == 1


def test_install_twice_wraps_once():
    m, calls = fake_module(0)
    freya_retry.install(m)
    first = m.api
    freya_retry.install(m)
    assert m.api is first


def test_outage_signature():
    assert freya_retry.is_outage([{"tools": []}, {"tools": []}])
    assert not freya_retry.is_outage([{"tools": []}, {"tools": ["verify_identity"]}])
    assert not freya_retry.is_outage([])
