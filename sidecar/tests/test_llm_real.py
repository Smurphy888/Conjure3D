"""
Tests for Phase J.4 — real-LLM scaffolding.

Two test groups:

  1. Prompt construction (llm_prompts.py): the system message includes
     every edit type, the examples round-trip through validate_chain
     (so we're never giving the model a malformed example), the user
     message conditionally includes sanity context.

  2. Backend install (llm.try_install_llama_backend): every failure
     branch returns a distinct status string. We mock
     llama_cpp_importable and find_model_path / LlamaCppBackend so
     these tests run with NO actual llama-cpp-python install or
     model file present.

There is no test that runs real inference — that requires a 4.4 GB
GGUF and minutes of CPU time. When llama-cpp-python is installed AND
a model is present, you can manually verify with:

    python -c "from llm_llama_cpp import LlamaCppBackend, default_model_path, grammar_path; \
               b = LlamaCppBackend(default_model_path(), grammar_path()); \
               c = b.generate('80mm vase, four zebra colors', 'vase'); \
               print(c.model_dump_json(indent=2))"
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import llm  # noqa: E402
import llm_prompts  # noqa: E402
from edit_chain_schema import CANONICAL_ORDER, validate_chain  # noqa: E402


# ── Prompt construction ─────────────────────────────────────────────────────


def test_system_message_lists_every_edit_type():
    """The model can only emit what it knows about. If we add an edit
    to the schema and forget to document it in the catalogue, the LLM
    will never use it. Catch that drift here."""
    sys_msg = llm_prompts.build_system_message()
    for op in CANONICAL_ORDER:
        assert op in sys_msg, f"system prompt missing edit type {op!r}"


def test_system_message_includes_color_split_modes():
    sys_msg = llm_prompts.build_system_message()
    for mode in ("zebra", "quarter", "none"):
        assert f'"{mode}"' in sys_msg, f"system prompt missing color_split mode {mode!r}"


def test_examples_are_valid_chains():
    """Every in-context example shown to the LLM must itself pass
    schema validation. Otherwise we're training the model to emit
    invalid output."""
    for user_msg, chain_data in llm_prompts.EXAMPLES:
        chain = validate_chain(chain_data)
        assert len(chain.edits) > 0, f"empty example chain for {user_msg!r}"


def test_user_message_includes_object_type():
    msg = llm_prompts.build_user_message("make a thing", object_type="vase")
    assert "Object type: vase" in msg
    assert "make a thing" in msg


def test_user_message_includes_sanity_when_present():
    sanity = {
        "manifold": False,
        "single_component": True,
        "normals_outward": True,
        "longest_dim_under_limit": True,
        "dims_mm": [100.0, 50.0, 30.0],
    }
    msg = llm_prompts.build_user_message("fix it", sanity=sanity)
    assert "Current longest dim: 100.0 mm" in msg
    assert "manifold=False" in msg


def test_user_message_handles_no_sanity_no_prompt_gracefully():
    msg = llm_prompts.build_user_message("")
    # Doesn't crash, doesn't include sanity, asks for a default chain
    assert "no request" in msg.lower()


def test_build_messages_returns_role_pairs():
    msgs = llm_prompts.build_messages("80mm vase", object_type="vase")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert "vase" in msgs[1]["content"]


# ── Install function — every failure branch ─────────────────────────────────


@pytest.fixture(autouse=True)
def _restore_default_backend():
    """Tests in this module monkey-patch the active backend. Restore
    after each test so the next test sees a clean mock."""
    saved = llm.get_backend()
    yield
    llm.set_backend(saved)


def test_install_returns_library_unavailable_when_llama_cpp_missing():
    """First failure branch: the library isn't installed (the common
    case for dev machines without llama-cpp-python). The status must
    be exactly 'library_unavailable' so the AI Editor can surface a
    specific user-facing hint."""
    with patch("llm_llama_cpp.llama_cpp_importable", return_value=False):
        status = llm.try_install_llama_backend()
    assert status == "library_unavailable"
    assert llm.backend_name() == "mock-keyword-router"


def test_install_returns_model_missing_when_no_gguf_on_disk():
    """Second failure branch: library is present but the model file
    hasn't been downloaded yet. This is the post-install / pre-J.5
    state — sidecar runs, AI Editor works, but on the mock."""
    with patch("llm_llama_cpp.llama_cpp_importable", return_value=True), \
         patch("llm_llama_cpp.find_model_path", return_value=None):
        status = llm.try_install_llama_backend()
    assert status == "model_missing"
    assert llm.backend_name() == "mock-keyword-router"


def test_install_returns_load_failed_when_warmup_raises():
    """Third failure branch: library AND model present, but Llama()
    blew up (OOM, corrupted GGUF, missing CUDA, etc.). The status
    carries the underlying reason so the user can diagnose."""
    from llm_llama_cpp import LlamaBackendUnavailable

    fake_path = Path("/tmp/fake.gguf")

    class _ExplodingBackend:
        name = "llama-cpp-qwen2.5-coder"

        def __init__(self, **kw):
            self.kw = kw

        def warm_up(self):
            raise LlamaBackendUnavailable("simulated OOM")

    with patch("llm_llama_cpp.llama_cpp_importable", return_value=True), \
         patch("llm_llama_cpp.find_model_path", return_value=fake_path), \
         patch("llm_llama_cpp.LlamaCppBackend", _ExplodingBackend):
        status = llm.try_install_llama_backend()
    assert status.startswith("load_failed: simulated OOM")
    assert llm.backend_name() == "mock-keyword-router"


def test_install_success_swaps_backend():
    """Happy path: every probe passes and warm_up() succeeds. The
    active backend becomes the fake we injected."""
    fake_path = Path("/tmp/fake.gguf")

    class _GoodBackend:
        name = "llama-cpp-qwen2.5-coder"

        def __init__(self, **kw):
            self.kw = kw

        def warm_up(self):
            return None

        def generate(self, user_prompt, object_type="solid_decorative", sanity=None):
            from edit_chain_schema import EditChain
            return EditChain(edits=[])

    with patch("llm_llama_cpp.llama_cpp_importable", return_value=True), \
         patch("llm_llama_cpp.find_model_path", return_value=fake_path), \
         patch("llm_llama_cpp.LlamaCppBackend", _GoodBackend):
        status = llm.try_install_llama_backend()
    assert status == "installed"
    assert llm.backend_name() == "llama-cpp-qwen2.5-coder"


def test_install_status_persists():
    """install_status() should return the most-recent attempt's result
    so the JSON-RPC backend_info endpoint can surface it."""
    with patch("llm_llama_cpp.llama_cpp_importable", return_value=False):
        llm.try_install_llama_backend()
    assert llm.install_status() == "library_unavailable"


# ── Dispatcher integration ──────────────────────────────────────────────────


def test_backend_info_dispatch_includes_install_status():
    """llm.backend_info now surfaces install_status so the AI Editor
    can show the user *why* we're on the mock."""
    import main

    # Force a deterministic state.
    with patch("llm_llama_cpp.llama_cpp_importable", return_value=False):
        llm.try_install_llama_backend()

    req = {"jsonrpc": "2.0", "id": 1, "method": "llm.backend_info", "params": {}}
    resp = main.dispatch(req)
    res = resp["result"]
    assert res["backend"] == "mock-keyword-router"
    assert res["install_status"] == "library_unavailable"
