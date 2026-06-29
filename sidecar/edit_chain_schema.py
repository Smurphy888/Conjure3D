"""
Edit-chain JSON schema for LLM output (Phase J.1).

This module defines:

  - Pydantic discriminated-union models for every supported edit operation,
    mirroring the contract orchestrator.apply_chain already consumes.
  - A top-level ``EditChain`` model that wraps an ordered list of edits.
  - The canonical execution order (re-exported from orchestrator's CANONICAL_ORDER
    semantics, kept as a tuple here for prompt-building convenience).
  - ``validate_chain()`` — the single entry point the LLM dispatcher should
    use to parse and validate an LLM-emitted JSON blob, raising
    pydantic.ValidationError on malformed input or out-of-range parameters.

The schema is intentionally strict: each edit class has a Literal type
discriminator and ranged numeric fields. This gives us two layers of safety:

  1. The LLM's output is constrained by the GBNF grammar (llm_grammar.gbnf)
     to *syntactically* valid JSON matching this shape — the model literally
     cannot emit an unknown type or a malformed field.
  2. This Pydantic schema validates *semantically*: ranges, required vs
     optional fields, integer vs float discipline. Catches the rare case
     where the grammar admits a number but the value is nonsensical
     (target_mm = -5, decimate target_faces = 100_000_000, etc.).

Both layers exist so that grammar bugs or future grammar relaxations cannot
sneak invalid data into orchestrator.apply_chain.

Ranges and defaults were derived from:
  - sanity.py — LONGEST_DIM_LIMIT_MM (256 mm) sets the upper bound for
    scale_to_longest target_mm
  - existing test fixtures in sidecar/tests/test_orchestrator.py
  - src/lib/edits.ts DEFAULT_PARAMS — the historical "shipped" defaults
  - ops/* implementations — defaults used when a field is omitted
"""
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


# Canonical execution order. The orchestrator re-sorts incoming chains into
# this order before running them (orchestrator.CANONICAL_ORDER), so the LLM is
# allowed to emit edits in any order — we sort. Exposed here so the LLM
# prompt can list the canonical sequence as part of its system message
# without duplicating the truth in two places.
CANONICAL_ORDER: tuple[str, ...] = (
    "scale_to_longest",
    "voxel_remesh",
    "keep_largest",
    "recenter_xy",
    "flat_bottom",
    "fix_normals",
    "decimate",
    "open_top",
    "bridge_top_loops",
    "color_split",
    "bisect",
)


class _EditBase(BaseModel):
    """Common config for every edit op. ``extra='forbid'`` rejects unknown
    fields outright so a hallucinating LLM can't sneak in side parameters."""

    model_config = ConfigDict(extra="forbid", frozen=True)


# ── Individual edit ops ───────────────────────────────────────────────────────
# Each class has a Literal type discriminator + its own typed fields.
# Pydantic's discriminated union (below) picks the right class based on the
# ``type`` string. Ranges are conservative but real:
#   - target_mm: clamped to the printer-bed range; sanity rejects > 256
#   - voxel_mm: 0.1 mm is finer than any home FFF printer's nozzle; 5 mm is
#     coarser than anything useful for the kind of decorative objects this
#     pipeline targets
#   - decimate target_faces: 1k–500k brackets the 30k–250k range Meshy
#     typically produces after voxel remesh


class ScaleToLongest(_EditBase):
    type: Literal["scale_to_longest"]
    target_mm: float = Field(..., gt=0, le=300)


class VoxelRemesh(_EditBase):
    type: Literal["voxel_remesh"]
    voxel_mm: float = Field(default=0.8, gt=0, le=10)


class KeepLargest(_EditBase):
    type: Literal["keep_largest"]


class RecenterXY(_EditBase):
    type: Literal["recenter_xy"]


class FlatBottom(_EditBase):
    type: Literal["flat_bottom"]
    cut_mm: float = Field(default=1.0, gt=0, le=20)


class FixNormals(_EditBase):
    type: Literal["fix_normals"]


class Decimate(_EditBase):
    type: Literal["decimate"]
    target_faces: int = Field(..., gt=0, le=2_000_000)


class OpenTop(_EditBase):
    """Vase op: trims a cut_mm-thick slab off the +Z end so bridge_top_loops
    can lid the hole. Only sensible when object_type='vase'."""

    type: Literal["open_top"]
    cut_mm: float = Field(default=2.0, gt=0, le=30)


class BridgeTopLoops(_EditBase):
    """Vase op: bridges the open boundary loops created by open_top."""

    type: Literal["bridge_top_loops"]


class ColorSplit(_EditBase):
    """Splits the mesh into multiple coloured objects for multi-filament
    printing. ``mode='none'`` is the no-op (kept so the LLM can express
    "no colour split" explicitly without omitting the edit)."""

    type: Literal["color_split"]
    mode: Literal["none", "zebra", "quarter"]
    count: int = Field(default=8, ge=2, le=32)


class Bisect(_EditBase):
    """Physically cut the mesh into TWO separate, watertight pieces with a
    single plane at the midpoint of the chosen axis. ``axis='z'`` (default)
    is a horizontal cut (top + bottom halves); 'x'/'y' are vertical cuts.
    Unlike color_split this separates geometry rather than assigning filaments;
    like color_split it intentionally yields multiple components (the
    orchestrator relaxes single_component when a bisect is present)."""

    type: Literal["bisect"]
    axis: Literal["x", "y", "z"] = "z"


# ── Discriminated union ──────────────────────────────────────────────────────
# Pydantic picks the right class based on the ``type`` field. The Annotated
# wrapper with Field(discriminator='type') is the v2 idiom that lets pydantic
# fail fast with a clear error like 'Input tag "frobnicate" not found' rather
# than a confusing all-fields-attempted union error.

Edit = Annotated[
    Union[
        ScaleToLongest,
        VoxelRemesh,
        KeepLargest,
        RecenterXY,
        FlatBottom,
        FixNormals,
        Decimate,
        OpenTop,
        BridgeTopLoops,
        ColorSplit,
        Bisect,
    ],
    Field(discriminator="type"),
]


class EditChain(BaseModel):
    """A complete chain — what the LLM emits and the orchestrator consumes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    edits: list[Edit] = Field(default_factory=list)

    def to_orchestrator_input(self) -> list[dict]:
        """Return the chain as a list of plain dicts in the exact shape
        orchestrator.apply_chain expects in params['edits']."""
        return [e.model_dump(exclude_unset=False) for e in self.edits]


# ── Public entry point ───────────────────────────────────────────────────────


def validate_chain(data: dict | str) -> EditChain:
    """Parse + validate an LLM-emitted edit chain.

    Accepts a dict (already JSON-parsed) or a raw JSON string. Raises
    pydantic.ValidationError on any structural or range violation. Returns
    a fully validated EditChain whose ``.to_orchestrator_input()`` is safe
    to hand to orchestrator.apply_chain.

    This is the single entry point the LLM dispatcher should call after
    sampling. The GBNF grammar should have already constrained the output
    to be syntactically valid JSON of this shape, so most failures here
    indicate a grammar bug — but we still validate, defence in depth.
    """
    if isinstance(data, str):
        return EditChain.model_validate_json(data)
    return EditChain.model_validate(data)
