"""Unit tests for llm_openai.py (mocked HTTP). Mirrors test_llm_openrouter."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import llm_openai as oai  # noqa: E402
from edit_chain_schema import EditChain  # noqa: E402

VALID = '{"edits":[{"type":"scale_to_longest","target_mm":80},{"type":"bisect","axis":"z"}]}'


class _Resp:
    def __init__(self, payload, ok=True, status_code=200, text=""):
        self._payload = payload
        self.ok = ok
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload


def _chat(content):
    return _Resp({"choices": [{"message": {"content": content}}]})


def _backend():
    return oai.OpenAIBackend(model="gpt-4o-mini", api_key="test-key")


def test_generate_parses_valid_chain():
    with patch("requests.post", return_value=_chat(VALID)):
        chain = _backend().generate("80mm then cut in half")
    assert isinstance(chain, EditChain)
    assert [e.type for e in chain.edits] == ["scale_to_longest", "bisect"]


def test_generate_strips_fences():
    with patch("requests.post", return_value=_chat("```json\n" + VALID + "\n```")):
        chain = _backend().generate("x")
    assert len(chain.edits) == 2


def test_generate_retries_once_then_succeeds():
    with patch("requests.post", side_effect=[_chat("nope"), _chat(VALID)]) as p:
        chain = _backend().generate("x")
    assert len(chain.edits) == 2
    assert p.call_count == 2


def test_api_error_body_surfaced():
    with patch("requests.post", return_value=_Resp({}, ok=False, status_code=401, text="bad key")):
        with pytest.raises(oai.OpenAIError) as ei:
            _backend().generate("x")
    assert "401" in str(ei.value)


def test_validate_accepts_200():
    with patch("requests.get", return_value=_Resp({}, ok=True, status_code=200)):
        _backend().validate()  # no raise


def test_validate_rejects_401():
    with patch("requests.get", return_value=_Resp({}, ok=False, status_code=401, text="x")):
        with pytest.raises(oai.OpenAIError) as ei:
            _backend().validate()
    assert "rejected" in str(ei.value).lower()


def test_validate_network_error_distinct(monkeypatch):
    import requests

    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("no net")

    monkeypatch.setattr("requests.get", boom)
    with pytest.raises(oai.OpenAIError) as ei:
        _backend().validate()
    assert "reach" in str(ei.value).lower()


def test_name_includes_model():
    assert _backend().name == "openai:gpt-4o-mini"


def test_key_roundtrip(monkeypatch):
    store = {}
    monkeypatch.setattr(oai.keyring, "set_password", lambda s, a, k: store.__setitem__(a, k))
    monkeypatch.setattr(oai.keyring, "get_password", lambda s, a: store.get(a))
    assert oai.has_openai_key() is False
    oai.set_openai_key("sk-xyz")
    assert oai.has_openai_key() is True
