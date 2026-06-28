"""
Tests for llm.py (Phase J.2).

Covers:

  - MockBackend keyword routing: each rule produces the chain shape we
    expect, and the produced chain validates through the J.1 schema.
  - Number extraction: "80mm", "120 mm", "8 colors" pulled out cleanly.
  - Defaults applied when the user prompt is empty or under-specified.
  - object_type override forces vase ops regardless of prompt.
  - JSON-RPC dispatcher (main.llm_generate_chain) returns the right
    shape on success and surfaces structured errors when the backend
    misbehaves.

These tests use the MockBackend directly. J.4 will add a separate test
suite for the llama.cpp backend (which will be slow / opt-in / skipped
without a model file present).
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import llm  # noqa: E402
import main  # noqa: E402
from edit_chain_schema import EditChain, validate_chain  # noqa: E402


# Every test that asks the mock for a chain should be able to assume the
# default backend is in place — we restore after each test in case some
# other test in the same process replaced it.
@pytest.fixture(autouse=True)
def _restore_default_backend():
    saved = llm.get_backend()
    llm.set_backend(llm.MockBackend())
    yield
    llm.set_backend(saved)


def _types(chain: EditChain) -> list[str]:
    return [e.type for e in chain.edits]


# ── Spine: every chain includes the canonical-clean ops ──────────────────────


def test_default_solid_chain_has_canonical_spine():
    chain = llm.generate_edit_chain("make it printable")
    t = _types(chain)
    # Spine ops appear in canonical order. flat_bottom is in for
    # solid_decorative; vase ops + color_split absent.
    assert t == [
        "scale_to_longest",
        "voxel_remesh",
        "keep_largest",
        "recenter_xy",
        "flat_bottom",
        "fix_normals",
        "decimate",
    ]


def test_default_chain_validates_through_schema():
    chain = llm.generate_edit_chain("anything")
    # Round-trip via the schema entry point — if the mock ever
    # constructs an Edit out of range, this fails loudly.
    validate_chain({"edits": chain.to_orchestrator_input()})


def test_empty_prompt_still_yields_usable_chain():
    chain = llm.generate_edit_chain("")
    assert len(chain.edits) >= 6  # spine present even with no instructions


# ── object_type routing ──────────────────────────────────────────────────────


def test_vase_object_type_appends_open_top_and_bridge():
    chain = llm.generate_edit_chain("make it nice", object_type="vase")
    t = _types(chain)
    assert "open_top" in t
    assert "bridge_top_loops" in t
    # Order: open_top precedes bridge_top_loops.
    assert t.index("open_top") < t.index("bridge_top_loops")
    # Vase does NOT get flat_bottom by default.
    assert "flat_bottom" not in t


def test_vase_keywords_in_prompt_imply_vase_chain():
    """The user can describe a vase even when the object_type is the
    fallback solid_decorative. The mock catches the intent from words."""
    chain = llm.generate_edit_chain("hollow it out as a vase")
    t = _types(chain)
    assert "open_top" in t
    assert "bridge_top_loops" in t


def test_flat_part_gets_flat_bottom():
    chain = llm.generate_edit_chain("flat panel", object_type="flat_part")
    assert "flat_bottom" in _types(chain)


# ── Number extraction ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "prompt,expected",
    [
        ("make it 80mm tall", 80.0),
        ("scale to 120 mm please", 120.0),
        ("about 45.5 mm height", 45.5),
        ("no number here", 80.0),  # default
        ("5000mm absurd", 300.0),  # clamped to schema max
    ],
)
def test_target_mm_extraction(prompt, expected):
    chain = llm.generate_edit_chain(prompt)
    scale = next(e for e in chain.edits if e.type == "scale_to_longest")
    assert scale.target_mm == pytest.approx(expected)


# ── Color-split routing ─────────────────────────────────────────────────────


def test_color_keyword_appends_zebra_split():
    chain = llm.generate_edit_chain("split into colors")
    t = _types(chain)
    assert t[-1] == "color_split"
    cs = chain.edits[-1]
    assert cs.mode == "zebra"


def test_quarter_keyword_picks_quarter_mode():
    chain = llm.generate_edit_chain("8 wedges in two colors")
    cs = chain.edits[-1]
    assert cs.type == "color_split"
    assert cs.mode == "quarter"


@pytest.mark.parametrize(
    "prompt,expected_count",
    [
        ("4 colors", 4),
        ("12 bands", 12),
        ("100 colors", 32),  # clamped to schema max
        ("just colorful", 8),  # default
    ],
)
def test_color_split_count_extraction(prompt, expected_count):
    chain = llm.generate_edit_chain(prompt)
    cs = chain.edits[-1]
    assert cs.type == "color_split"
    assert cs.count == expected_count


def test_no_color_keyword_omits_color_split():
    chain = llm.generate_edit_chain("just make it 60mm tall")
    assert "color_split" not in _types(chain)


@pytest.mark.parametrize(
    "prompt",
    [
        "vase, 80mm tall, single color",
        "solid color vase",
        "one colour please",
        "monochrome model",
        "80mm, no color split",
        "1 color",
    ],
)
def test_single_color_phrases_suppress_color_split(prompt):
    """Explicit single-color intent must NOT produce a color_split edit.
    Regression for: 'single color' matching the bare 'color' needle."""
    chain = llm.generate_edit_chain(prompt, object_type="vase")
    assert "color_split" not in _types(chain), (
        f"color_split unexpectedly generated for prompt: {prompt!r}"
    )


# ── Style / detail routing ──────────────────────────────────────────────────


def test_light_keyword_lowers_decimate_target():
    chain = llm.generate_edit_chain("make it lighter, less detail")
    decimate = next(e for e in chain.edits if e.type == "decimate")
    assert decimate.target_faces == 20_000


def test_detail_keyword_raises_decimate_target():
    chain = llm.generate_edit_chain("preserve fine detail")
    decimate = next(e for e in chain.edits if e.type == "decimate")
    assert decimate.target_faces == 100_000


def test_default_decimate_target_when_neutral():
    chain = llm.generate_edit_chain("normal print")
    decimate = next(e for e in chain.edits if e.type == "decimate")
    assert decimate.target_faces == 50_000


# ── Backend swap mechanics ──────────────────────────────────────────────────


class _StaticBackend:
    """A fake backend that always returns the same chain. Used to verify
    set_backend / get_backend / backend_name work as advertised — the
    same plumbing J.4 uses to install the real llama.cpp backend."""

    name = "static-test"

    def generate(self, user_prompt, object_type="solid_decorative", sanity=None):
        return EditChain(edits=[])


def test_set_backend_swaps_active_backend():
    llm.set_backend(_StaticBackend())
    assert llm.backend_name() == "static-test"
    chain = llm.generate_edit_chain("anything")
    assert chain.edits == []


def test_backend_name_default_is_mock():
    assert llm.backend_name() == "mock-keyword-router"


# ── JSON-RPC dispatcher integration ─────────────────────────────────────────


def test_dispatch_llm_generate_chain_success():
    """The main.py dispatcher must return the {ok,edits,backend}
    envelope, with edits already in the orchestrator-input shape so the
    frontend can hand them straight to edit.apply_chain."""
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "llm.generate_chain",
        "params": {"user_prompt": "tall vase, 100mm", "object_type": "vase"},
    }
    resp = main.dispatch(req)
    assert resp["id"] == 1
    res = resp["result"]
    assert res["ok"] is True
    assert res["backend"] == "mock-keyword-router"
    assert isinstance(res["edits"], list)
    assert any(e["type"] == "open_top" for e in res["edits"])


def test_dispatch_llm_backend_info():
    """backend_info now carries install_status (Phase J.4 addition) so
    the AI Editor can surface "library_unavailable" / "model_missing"
    / "load_failed" alongside the backend name. Assert on the fields
    we care about, not the whole dict, so future additions don't break."""
    req = {"jsonrpc": "2.0", "id": 2, "method": "llm.backend_info", "params": {}}
    resp = main.dispatch(req)
    res = resp["result"]
    assert res["backend"] == "mock-keyword-router"
    assert "install_status" in res


def test_dispatch_translates_backend_error_to_structured_error():
    """If the backend raises a non-ValidationError (real llama.cpp can
    OOM, etc.), the dispatcher must return error_code=backend_error
    rather than letting the dispatcher's generic -32603 path fire.
    The frontend's UI copy branches on error_code."""

    class _Boom:
        name = "boom"

        def generate(self, *a, **kw):
            raise RuntimeError("model exploded")

    llm.set_backend(_Boom())
    req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "llm.generate_chain",
        "params": {"user_prompt": "x"},
    }
    resp = main.dispatch(req)
    res = resp["result"]
    assert res["ok"] is False
    assert res["error_code"] == "backend_error"
    assert "model exploded" in res["message"]


def test_dispatch_translates_validation_error_to_schema_violation():
    """A backend that returns an out-of-range value gets caught by
    Pydantic at construction (good), and the dispatcher labels it
    schema_violation so the UI can distinguish 'LLM said something
    weird' from 'LLM crashed'."""
    from pydantic import ValidationError

    class _BadSchema:
        name = "bad-schema"

        def generate(self, *a, **kw):
            # Simulate the LLM emitting a value outside the schema.
            # We raise a real ValidationError so the dispatcher's
            # except-branch fires.
            try:
                from edit_chain_schema import ScaleToLongest
                ScaleToLongest(type="scale_to_longest", target_mm=-5)
            except ValidationError:
                raise
            return EditChain(edits=[])

    llm.set_backend(_BadSchema())
    req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "llm.generate_chain",
        "params": {"user_prompt": "x"},
    }
    resp = main.dispatch(req)
    res = resp["result"]
    assert res["ok"] is False
    assert res["error_code"] == "schema_violation"
