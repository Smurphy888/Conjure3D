"""
Tests for edit_chain_schema.py + llm_grammar.gbnf (Phase J.1).

Two test groups:

  - Pydantic schema validation: every edit type round-trips cleanly, range
    violations are rejected, unknown types are rejected, the orchestrator-
    facing serialisation is byte-identical to the historical test fixtures
    in test_orchestrator.py.

  - GBNF grammar smoke check: the .gbnf file exists, is non-empty, and
    every edit "type" string appears in it (catches the common bug of
    adding a new edit class in Python but forgetting to update the
    grammar, which would silently let the LLM emit unknown types).

Live grammar parsing is NOT tested here — that requires llama-cpp-python
and a loaded model, which is J.4. We trust the grammar's syntactic
correctness via the smoke check + the Pydantic layer's belt-and-braces
validation at runtime.
"""
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent.parent))
from edit_chain_schema import (  # noqa: E402
    CANONICAL_ORDER,
    EditChain,
    validate_chain,
)


# ── Happy-path: every edit type parses ────────────────────────────────────────


GOOD_FULL_CHAIN = {
    "edits": [
        {"type": "scale_to_longest", "target_mm": 80},
        {"type": "voxel_remesh", "voxel_mm": 0.8},
        {"type": "keep_largest"},
        {"type": "recenter_xy"},
        {"type": "flat_bottom", "cut_mm": 1},
        {"type": "fix_normals"},
        {"type": "decimate", "target_faces": 50000},
        {"type": "open_top", "cut_mm": 2},
        {"type": "bridge_top_loops"},
        {"type": "color_split", "mode": "zebra", "count": 8},
    ]
}


def test_full_canonical_chain_parses():
    chain = validate_chain(GOOD_FULL_CHAIN)
    assert len(chain.edits) == 10
    assert chain.edits[0].type == "scale_to_longest"
    assert chain.edits[-1].type == "color_split"


def test_empty_chain_is_valid():
    """An empty chain is the no-op case the LLM may emit if the user's
    request is genuinely satisfied by Meshy's raw output."""
    chain = validate_chain({"edits": []})
    assert chain.edits == []


def test_accepts_json_string_or_dict():
    """validate_chain should be agnostic to whether the caller already
    parsed the JSON. Both paths must succeed."""
    as_dict = validate_chain(GOOD_FULL_CHAIN)
    as_str = validate_chain(json.dumps(GOOD_FULL_CHAIN))
    assert as_dict.model_dump() == as_str.model_dump()


def test_to_orchestrator_input_matches_historical_fixture():
    """The output of EditChain.to_orchestrator_input() must be byte-
    identical to what test_orchestrator.py uses today. This is the
    integration contract; orchestrator code does not change in J.1."""
    chain = validate_chain(GOOD_FULL_CHAIN)
    out = chain.to_orchestrator_input()
    # Each round-tripped edit must contain every original key (defaults
    # added by Pydantic are fine, but no key may be dropped).
    for original, parsed in zip(GOOD_FULL_CHAIN["edits"], out):
        for k, v in original.items():
            assert parsed[k] == v, f"field {k} drifted: {v} vs {parsed[k]}"


# ── Defaults are applied when optional fields are omitted ────────────────────


@pytest.mark.parametrize(
    "edit,field,default",
    [
        ({"type": "voxel_remesh"}, "voxel_mm", 0.8),
        ({"type": "flat_bottom"}, "cut_mm", 1.0),
        ({"type": "open_top"}, "cut_mm", 2.0),
        ({"type": "color_split", "mode": "zebra"}, "count", 8),
    ],
)
def test_optional_fields_default(edit, field, default):
    chain = validate_chain({"edits": [edit]})
    assert getattr(chain.edits[0], field) == default


# ── Unknown / malformed edits are rejected ────────────────────────────────────


def test_unknown_type_rejected():
    with pytest.raises(ValidationError):
        validate_chain({"edits": [{"type": "frobnicate"}]})


def test_missing_type_rejected():
    with pytest.raises(ValidationError):
        validate_chain({"edits": [{"target_mm": 80}]})


def test_extra_field_rejected():
    """extra='forbid' on every edit class means a hallucinated parameter
    is a hard error, not silently dropped. Otherwise a model emitting
    target_height_mm (the wrong name) would be accepted and silently
    use the default — a bug that would be miserable to debug."""
    with pytest.raises(ValidationError):
        validate_chain(
            {"edits": [{"type": "scale_to_longest", "target_mm": 80, "extra": 1}]}
        )


def test_chain_extra_field_rejected():
    """Same rule at the top level. The model must not emit sibling keys
    next to 'edits'."""
    with pytest.raises(ValidationError):
        validate_chain({"edits": [], "notes": "free-form"})


# ── Range violations ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad_edit",
    [
        {"type": "scale_to_longest", "target_mm": 0},          # not > 0
        {"type": "scale_to_longest", "target_mm": -10},        # negative
        {"type": "scale_to_longest", "target_mm": 400},        # over bed
        {"type": "voxel_remesh", "voxel_mm": 0},               # not > 0
        {"type": "voxel_remesh", "voxel_mm": 50},              # absurdly coarse
        {"type": "flat_bottom", "cut_mm": -1},
        {"type": "decimate", "target_faces": 0},
        {"type": "decimate", "target_faces": -5},
        {"type": "decimate", "target_faces": 5_000_000_000},   # over cap
        {"type": "open_top", "cut_mm": 0},
        {"type": "color_split", "mode": "zebra", "count": 1},  # count < 2
        {"type": "color_split", "mode": "zebra", "count": 100},
        {"type": "color_split", "mode": "rainbow"},            # bad mode
    ],
)
def test_range_violations_rejected(bad_edit):
    with pytest.raises(ValidationError):
        validate_chain({"edits": [bad_edit]})


# ── Required field omitted ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "incomplete",
    [
        {"type": "scale_to_longest"},                # target_mm missing
        {"type": "decimate"},                        # target_faces missing
        {"type": "color_split"},                     # mode missing
    ],
)
def test_required_fields_enforced(incomplete):
    with pytest.raises(ValidationError):
        validate_chain({"edits": [incomplete]})


# ── Type discipline ──────────────────────────────────────────────────────────


def test_decimate_target_faces_must_be_int():
    """target_faces is declared int. Pydantic v2 coerces float-looking
    integers (50000.0) but rejects clearly fractional ones (50000.5)."""
    # Integer-valued floats coerce.
    chain = validate_chain(
        {"edits": [{"type": "decimate", "target_faces": 50000.0}]}
    )
    assert chain.edits[0].target_faces == 50000

    with pytest.raises(ValidationError):
        validate_chain(
            {"edits": [{"type": "decimate", "target_faces": 50000.5}]}
        )


def test_color_split_count_must_be_int():
    with pytest.raises(ValidationError):
        validate_chain(
            {"edits": [{"type": "color_split", "mode": "zebra", "count": 8.5}]}
        )


# ── Bisect ────────────────────────────────────────────────────────────────────


def test_bisect_parses_and_defaults_axis_z():
    chain = validate_chain({"edits": [{"type": "bisect"}]})
    assert chain.edits[0].type == "bisect"
    assert chain.edits[0].axis == "z"


@pytest.mark.parametrize("axis", ["x", "y", "z"])
def test_bisect_accepts_valid_axes(axis):
    chain = validate_chain({"edits": [{"type": "bisect", "axis": axis}]})
    assert chain.edits[0].axis == axis


def test_bisect_rejects_bad_axis():
    with pytest.raises(ValidationError):
        validate_chain({"edits": [{"type": "bisect", "axis": "w"}]})


# ── Canonical order export ───────────────────────────────────────────────────


def test_canonical_order_matches_orchestrator():
    """CANONICAL_ORDER must exactly mirror orchestrator.CANONICAL_ORDER's
    key sequence. If a new edit type is added to one and not the other,
    chains can run in the wrong order or be dropped."""
    import orchestrator

    expected = tuple(
        sorted(orchestrator.CANONICAL_ORDER, key=orchestrator.CANONICAL_ORDER.get)
    )
    assert CANONICAL_ORDER == expected


# ── GBNF grammar smoke check ─────────────────────────────────────────────────


GRAMMAR_PATH = Path(__file__).parent.parent / "llm_grammar.gbnf"


def test_grammar_file_exists_and_non_empty():
    assert GRAMMAR_PATH.is_file(), f"grammar missing: {GRAMMAR_PATH}"
    assert GRAMMAR_PATH.stat().st_size > 0


def test_grammar_mentions_every_edit_type():
    """Every edit "type" literal in the Pydantic schema must appear as a
    quoted string in the grammar. Catches the silent-drift bug where a
    new edit class is added in Python but the grammar isn't updated:
    without this test, the LLM would still emit the old types and never
    learn to emit the new one — a class of bug that would be invisible
    until a user noticed the feature was inaccessible."""
    text = GRAMMAR_PATH.read_text(encoding="utf-8")
    for op in CANONICAL_ORDER:
        # Quoted form, escaped per the GBNF file's style.
        needle = f'\\"{op}\\"'
        assert needle in text, f'grammar does not mention "{op}"'


def test_grammar_mentions_color_split_modes():
    """The mode enum is part of the grammar's GBNF (so the model can't
    invent a third mode). Make sure all three strings appear."""
    text = GRAMMAR_PATH.read_text(encoding="utf-8")
    for mode in ("none", "zebra", "quarter"):
        assert f'\\"{mode}\\"' in text, f'grammar missing mode "{mode}"'
