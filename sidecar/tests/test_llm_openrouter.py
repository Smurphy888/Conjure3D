"""
Tests for llm_openrouter.py (Phase J.6 cloud backend).

These are UNIT tests with requests.post mocked — they prove the parsing /
retry / guard logic, NOT that a real OpenRouter call works (that needs a live
key and is done as a manual verification step). The Tripo lesson: green mocked
tests are not live verification.
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import llm_openrouter as orouter  # noqa: E402
from edit_chain_schema import EditChain  # noqa: E402

VALID = (
    '{"edits":[{"type":"scale_to_longest","target_mm":80},'
    '{"type":"bisect","axis":"z"}]}'
)


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
    return orouter.OpenRouterBackend(
        model="qwen/qwen-2.5-coder-32b-instruct", api_key="test-key"
    )


def test_generate_parses_valid_chain():
    with patch("requests.post", return_value=_chat(VALID)):
        chain = _backend().generate("80mm then cut in half")
    assert isinstance(chain, EditChain)
    assert [e.type for e in chain.edits] == ["scale_to_longest", "bisect"]


def test_generate_strips_markdown_fences():
    with patch("requests.post", return_value=_chat("```json\n" + VALID + "\n```")):
        chain = _backend().generate("x")
    assert len(chain.edits) == 2


def test_generate_extracts_json_amid_prose():
    msg = "Sure! Here is your chain:\n" + VALID + "\nHope that helps."
    with patch("requests.post", return_value=_chat(msg)):
        chain = _backend().generate("x")
    assert chain.edits[0].type == "scale_to_longest"


def test_generate_retries_once_then_succeeds():
    with patch("requests.post", side_effect=[_chat("not json"), _chat(VALID)]) as p:
        chain = _backend().generate("x")
    assert len(chain.edits) == 2
    assert p.call_count == 2


def test_generate_raises_after_retry_exhausted():
    with patch("requests.post", side_effect=[_chat("nope"), _chat("still nope")]):
        with pytest.raises(orouter.OpenRouterError):
            _backend().generate("x")


def test_anthropic_model_rejected_at_construction():
    with pytest.raises(orouter.OpenRouterError):
        orouter.OpenRouterBackend(model="anthropic/claude-3.5-sonnet", api_key="k")


def test_api_error_body_surfaced():
    err = _Resp({}, ok=False, status_code=401, text="invalid key")
    with patch("requests.post", return_value=err):
        with pytest.raises(orouter.OpenRouterError) as ei:
            _backend().generate("x")
    assert "401" in str(ei.value)


def test_warm_up_requires_key(monkeypatch):
    monkeypatch.setattr(orouter.keyring, "get_password", lambda *a: None)
    with pytest.raises(orouter.OpenRouterError):
        orouter.OpenRouterBackend().warm_up()


def test_generate_strips_stray_root_fields():
    # Regression: cloud LLMs sometimes put edit fields at the JSON root alongside
    # "edits" — e.g. {"type":"scale_to_longest","target_mm":200,"edits":[...]}.
    # EditChain has extra="forbid", so those stray keys caused a ValidationError.
    # _to_chain_dict must strip them and recover successfully.
    stray = '{"type":"scale_to_longest","target_mm":200,"edits":[{"type":"bisect","axis":"z"}]}'
    with patch("requests.post", return_value=_chat(stray)):
        chain = _backend().generate("split in half")
    assert [e.type for e in chain.edits] == ["bisect"]


def test_generate_wraps_single_edit_without_array():
    # Regression: model returns a bare edit object with no "edits" wrapper —
    # e.g. {"type":"scale_to_longest","target_mm":150} — when the user asks for
    # a single change. _to_chain_dict must wrap it in a list automatically.
    single = '{"type":"scale_to_longest","target_mm":150}'
    with patch("requests.post", return_value=_chat(single)):
        chain = _backend().generate("scale to 150mm")
    assert len(chain.edits) == 1
    assert chain.edits[0].type == "scale_to_longest"


def test_generate_accepts_alternative_key_operations():
    # Model uses "operations" instead of "edits" as the collection key.
    alt = '{"operations":[{"type":"scale_to_longest","target_mm":100}]}'
    with patch("requests.post", return_value=_chat(alt)):
        chain = _backend().generate("scale to 100mm")
    assert chain.edits[0].type == "scale_to_longest"


def test_generate_unwraps_nested_object_wrapper():
    # Model wraps the whole chain one level deep, e.g. {"edit_chain":{...}}.
    # _recover_edits unwraps single-key wrappers and recurses.
    nested = '{"edit_chain":{"edits":[{"type":"keep_largest"}]}}'
    with patch("requests.post", return_value=_chat(nested)):
        chain = _backend().generate("keep the largest piece")
    assert [e.type for e in chain.edits] == ["keep_largest"]


def test_generate_recovers_arbitrary_collection_key():
    # A list of edit-shaped dicts under a key we don't enumerate ("plan" IS
    # enumerated, so use something off-list to exercise the value-scan branch).
    weird = '{"the_chain":[{"type":"fix_normals"},{"type":"keep_largest"}]}'
    with patch("requests.post", return_value=_chat(weird)):
        chain = _backend().generate("clean it up")
    assert [e.type for e in chain.edits] == ["fix_normals", "keep_largest"]


def test_to_chain_dict_error_names_the_offending_shape():
    # Regression for the qwen-coder malformed-quote reply
    # {"edits:[{type":...} — valid JSON, but the junk key means no edits are
    # recoverable. The error MUST surface the actual keys so the failure is
    # self-diagnosing from the UI/log instead of an opaque "no edits key".
    broken = '{"edits:[{type":"scale_to_longest","target_mm":256}'
    with pytest.raises(ValueError) as ei:
        orouter._to_chain_dict(broken)
    msg = str(ei.value)
    assert "top-level keys" in msg
    assert "edits:[{type" in msg


def test_extract_balanced_object_ignores_braces_in_strings():
    nested = 'prefix {"edits":[{"type":"keep_largest"}]} suffix'
    assert (
        orouter._extract_json_object(nested)
        == '{"edits":[{"type":"keep_largest"}]}'
    )


def test_name_includes_model():
    assert _backend().name == "openrouter:qwen/qwen-2.5-coder-32b-instruct"


def test_key_roundtrip(monkeypatch):
    store = {}
    monkeypatch.setattr(orouter.keyring, "set_password", lambda s, a, k: store.__setitem__(a, k))
    monkeypatch.setattr(orouter.keyring, "get_password", lambda s, a: store.get(a))
    assert orouter.has_openrouter_key() is False
    orouter.set_openrouter_key("sk-or-xyz")
    assert orouter.has_openrouter_key() is True
