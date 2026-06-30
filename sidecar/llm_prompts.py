"""
Prompt construction for the real LLM backend (Phase J.4).

This module is intentionally free of any llama-cpp-python (or other
inference library) dependency. It produces:

  - the system message that frames the task, documents the edit
    vocabulary, and gives a couple of in-context examples
  - the user message wrapper that injects context (object_type, current
    sanity if any) alongside the raw natural-language request

The two are returned as a list of {role, content} dicts ready for
llama-cpp-python's create_chat_completion(messages=[...]), which applies
the model's own chat template (ChatML for Qwen2.5-Coder).

Design choices:

  * The edit catalogue inside the system prompt is sourced from a single
    constant here. If you add an edit type, update this constant AND
    edit_chain_schema.py AND llm_grammar.gbnf — the grammar smoke test
    enforces the latter two; the LLM cannot learn about an op not
    documented here.
  * Examples are kept short (2 small chains) to leave room in the
    context window. Qwen2.5-Coder-7B handles 32k tokens but we want
    every prompt to be cheap; the GBNF grammar carries most of the
    correctness guarantee, not the few-shot examples.
  * The system prompt does NOT plead with the model to emit valid JSON
    — the GBNF grammar makes that a hard constraint at the sampler
    level, so the prompt focuses on *content* quality instead.
"""
from __future__ import annotations

import json
from typing import Any

from edit_chain_schema import CANONICAL_ORDER


# ── Edit catalogue (rendered into the system prompt) ────────────────────────
#
# Each entry: (op, one-line description, parameter sketch). The parameter
# sketch is rendered verbatim into the prompt so the model can see allowed
# values inline rather than having to read JSON Schema. Keep ranges in
# sync with edit_chain_schema.py.

_EDIT_CATALOGUE: list[tuple[str, str, str]] = [
    (
        "scale_to_longest",
        "scale the mesh so its longest dimension equals target_mm",
        '{"type":"scale_to_longest","target_mm":<float 1–300>}',
    ),
    (
        "voxel_remesh",
        "rebuild as a watertight voxel mesh; cures non-manifold + mesh-soup input",
        '{"type":"voxel_remesh","voxel_mm":<float 0.1–10, default 0.8>}',
    ),
    (
        "keep_largest",
        "discard small disconnected pieces; keep only the largest connected component",
        '{"type":"keep_largest"}',
    ),
    (
        "recenter_xy",
        "translate so the mesh is centred on X and Y, base at Z=0",
        '{"type":"recenter_xy"}',
    ),
    (
        "flat_bottom",
        "cut the bottom flat so the part sits on the bed",
        '{"type":"flat_bottom","cut_mm":<float 0.1–20, default 1.0>}',
    ),
    (
        "fix_normals",
        "make all face normals point outward (essential for slicing)",
        '{"type":"fix_normals"}',
    ),
    (
        "decimate",
        "reduce face count; lower target = lighter, less detail",
        '{"type":"decimate","target_faces":<int 1000–2000000>}',
    ),
    (
        "open_top",
        "VASE ONLY: trim a slab off the top so the model is open at +Z",
        '{"type":"open_top","cut_mm":<float 0.1–30, default 2.0>}',
    ),
    (
        "bridge_top_loops",
        "VASE ONLY: bridge the loops left by open_top to close the upper rim",
        '{"type":"bridge_top_loops"}',
    ),
    (
        "color_split",
        'split into multi-filament groups: "zebra" = N horizontal bands, '
        '"quarter" = 4 geometric wedges (same filament), "none" = no split',
        '{"type":"color_split","mode":"zebra"|"quarter"|"none","count":<int 2–32, default 8>}',
    ),
    (
        "bisect",
        "physically CUT the model into two separate watertight pieces with one "
        'plane: "z" = horizontal cut (top/bottom halves), "x"/"y" = vertical. '
        "Use this for “cut/split in half”, “two pieces”, “separate halves”. "
        "Not for colour — that's color_split.",
        '{"type":"bisect","axis":"z"|"x"|"y"}',
    ),
]


def _catalogue_block() -> str:
    """Render the edit catalogue as bullet lines for the system prompt."""
    lines = []
    for op, desc, sketch in _EDIT_CATALOGUE:
        lines.append(f"- {op}: {desc}")
        lines.append(f"    shape: {sketch}")
    return "\n".join(lines)


# ── Examples ────────────────────────────────────────────────────────────────
#
# In-context examples. Kept short. Each must be a valid chain under the
# J.1 schema — there's a test that round-trips them through validate_chain.

EXAMPLES: list[tuple[str, dict]] = [
    (
        '"make it 80mm tall, vase, watertight"',
        {
            "edits": [
                {"type": "scale_to_longest", "target_mm": 80},
                {"type": "voxel_remesh", "voxel_mm": 0.8},
                {"type": "keep_largest"},
                {"type": "recenter_xy"},
                {"type": "fix_normals"},
                {"type": "decimate", "target_faces": 50000},
                {"type": "open_top", "cut_mm": 2.0},
                {"type": "bridge_top_loops"},
            ]
        },
    ),
    (
        '"smaller, less detail, four zebra colours"',
        {
            "edits": [
                {"type": "scale_to_longest", "target_mm": 60},
                {"type": "voxel_remesh", "voxel_mm": 0.8},
                {"type": "keep_largest"},
                {"type": "recenter_xy"},
                {"type": "flat_bottom", "cut_mm": 1.0},
                {"type": "fix_normals"},
                {"type": "decimate", "target_faces": 20000},
                {"type": "color_split", "mode": "zebra", "count": 4},
            ]
        },
    ),
    (
        '"scale to 80mm and split in half on z axis"',
        {
            "edits": [
                {"type": "scale_to_longest", "target_mm": 80},
                {"type": "voxel_remesh", "voxel_mm": 0.8},
                {"type": "keep_largest"},
                {"type": "recenter_xy"},
                {"type": "fix_normals"},
                {"type": "decimate", "target_faces": 50000},
                {"type": "bisect", "axis": "z"},
            ]
        },
    ),
]


def _examples_block() -> str:
    out = []
    for user_msg, chain in EXAMPLES:
        out.append(f"User request: {user_msg}")
        out.append(f"Edit chain:   {json.dumps(chain, separators=(',', ':'))}")
        out.append("")
    return "\n".join(out).rstrip()


# ── Public API ──────────────────────────────────────────────────────────────


def build_system_message() -> str:
    """The system message — task framing, catalogue, examples, canonical
    order note. Stable across requests; the model sees the same string
    every call which keeps llama.cpp's KV-cache hot."""
    canonical = " → ".join(CANONICAL_ORDER)
    return (
        "You convert natural-language 3D model edit requests into a JSON\n"
        "edit chain for Conjure3D's auto-clean pipeline. Output a single JSON\n"
        "object of the exact shape:\n"
        "\n"
        "  {\"edits\":[ ... ]}\n"
        "\n"
        "Each entry in the array is one edit operation. Use ONLY the\n"
        "operations listed below; their JSON shapes are pinned by a\n"
        "grammar — emitting an unknown type, wrong field, or out-of-range\n"
        "value will fail.\n"
        "\n"
        "Available operations:\n"
        f"{_catalogue_block()}\n"
        "\n"
        "Canonical execution order (the orchestrator re-sorts to this, so\n"
        "you can emit ops in any order, but listing them in canonical\n"
        "order keeps the chain readable):\n"
        f"  {canonical}\n"
        "\n"
        "Examples:\n"
        f"{_examples_block()}\n"
        "\n"
        "Now emit the JSON edit chain for the user's request. Output ONLY\n"
        "the JSON object — no prose, no markdown fences."
    )


def build_user_message(
    user_prompt: str,
    object_type: str = "solid_decorative",
    sanity: dict[str, Any] | None = None,
) -> str:
    """The per-request user message. Bakes in the object type and (if
    we have one) the current sanity snapshot so the model can react to
    the actual state of the mesh — e.g. "manifold=False" hints at
    adding voxel_remesh+fix_normals."""
    lines = [f"Object type: {object_type}"]
    if sanity:
        dims = sanity.get("dims_mm")
        if dims:
            try:
                longest = float(max(dims))
                lines.append(f"Current longest dim: {longest:.1f} mm")
            except (TypeError, ValueError):
                pass
        flags = []
        for key in ("manifold", "single_component", "normals_outward", "longest_dim_under_limit"):
            if key in sanity:
                flags.append(f"{key}={sanity[key]}")
        if flags:
            lines.append("Current sanity: " + ", ".join(flags))
    lines.append("")
    lines.append(f"User request: {user_prompt.strip() or '(no request — produce a sensible default chain)'}")
    return "\n".join(lines)


def build_messages(
    user_prompt: str,
    object_type: str = "solid_decorative",
    sanity: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Return the [{role, content}] list ready for create_chat_completion."""
    return [
        {"role": "system", "content": build_system_message()},
        {"role": "user", "content": build_user_message(user_prompt, object_type, sanity)},
    ]
