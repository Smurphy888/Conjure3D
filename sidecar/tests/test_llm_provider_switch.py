"""
Dispatcher-level tests for llm.set_provider's validate-at-switch gating.

This is the regression guard for the trap a user hit: a bad cloud key used to
"succeed" (only presence was checked), the app left degraded-state, and the
recovery UI vanished. Now a cloud switch is GATED on a live validate() — a bad
key must return ok:False and leave the current backend untouched.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import llm  # noqa: E402
import main  # noqa: E402


class _Resp:
    def __init__(self, status_code=200, ok=True, text=""):
        self.status_code = status_code
        self.ok = ok
        self.text = text


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    saved = llm.get_backend()
    llm.set_backend(llm.MockBackend())
    # In-memory settings so the test never touches the real settings.json.
    store = {"version": 1, "wizard": {}, "llm_provider": "local", "llm_model": None}
    monkeypatch.setattr(main, "read_settings", lambda *a, **k: dict(store))
    monkeypatch.setattr(main, "write_settings", lambda data, *a, **k: store.update(data))
    # Never trigger a real (slow / crashy) llama load when reverting to local.
    monkeypatch.setattr(llm, "try_install_llama_backend", lambda *a, **k: "model_missing")
    yield
    llm.set_backend(saved)


def _set_provider(params):
    return main.dispatch(
        {"jsonrpc": "2.0", "id": 1, "method": "llm.set_provider", "params": params}
    )["result"]


def test_openrouter_valid_key_switches(monkeypatch):
    monkeypatch.setattr("llm_openrouter.keyring.get_password", lambda s, a: "sk-or-v1-good")
    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp(200, True))
    res = _set_provider({"provider": "openrouter"})
    assert res["ok"] is True
    assert res["degraded"] is False
    assert llm.backend_name().startswith("openrouter:")


def test_openai_valid_key_switches(monkeypatch):
    monkeypatch.setattr("llm_openai.keyring.get_password", lambda s, a: "sk-good")
    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp(200, True))
    res = _set_provider({"provider": "openai"})
    assert res["ok"] is True
    assert llm.backend_name().startswith("openai:")


def test_bad_key_does_not_switch_and_stays_on_mock(monkeypatch):
    # The exact trap: a wrong key (validate 401) must NOT switch the backend.
    monkeypatch.setattr("llm_openrouter.keyring.get_password", lambda s, a: "sk-wrong")
    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp(401, False, '{"error":"no"}'))
    res = _set_provider({"provider": "openrouter"})
    assert res["ok"] is False
    assert "401" in res["message"] or "rejected" in res["message"].lower()
    assert llm.backend_name() == "mock-keyword-router"  # unchanged


def test_missing_key_does_not_switch(monkeypatch):
    monkeypatch.setattr("llm_openai.keyring.get_password", lambda s, a: None)
    res = _set_provider({"provider": "openai"})
    assert res["ok"] is False
    assert llm.backend_name() == "mock-keyword-router"


def test_revert_to_local_needs_no_key():
    res = _set_provider({"provider": "local"})
    assert res["ok"] is True
    assert res["provider"] == "local"


def test_unknown_provider_rejected():
    resp = main.dispatch(
        {"jsonrpc": "2.0", "id": 9, "method": "llm.set_provider", "params": {"provider": "bogus"}}
    )
    # ValueError -> dispatcher's internal-error path (not a structured result).
    assert "error" in resp
