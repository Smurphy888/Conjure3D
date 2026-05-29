"""
Natural-language edit-chain generation (Phase J.2 — mocked backend).

This module is the seam between the LLM and the rest of the system.
Everything upstream (Tauri / React) calls a single entry point,
``generate_edit_chain(...)``, and gets back a validated :class:`EditChain`
which can be handed to ``orchestrator.apply_chain`` unchanged.

Backend abstraction
-------------------

The LLM lives behind the :class:`Backend` Protocol so we can swap the
implementation without touching the dispatcher or the UI:

  - J.2 (this commit): :class:`MockBackend` — keyword-routing pseudo-LLM
    that returns sensible canned chains. Deterministic, instant, no
    model file required. Lets J.3 build the entire UI before J.4 lands
    real inference.

  - J.4: ``LlamaCppBackend`` will load the Qwen2.5-Coder GGUF via
    llama-cpp-python and emit chains through GBNF-constrained sampling.
    It replaces ``_backend`` at import time when the model is available.

  - J.6: ``OpenAIBackend`` / ``OpenRouterBackend`` for the cloud escape
    hatch, selected via settings.

The schema contract (:mod:`edit_chain_schema`) is the same for every
backend, so a regression in one cannot quietly corrupt downstream state.

Error handling
--------------

``generate_edit_chain`` never raises across the JSON-RPC boundary — the
dispatcher in :mod:`main` wraps the result. The Backend is allowed to
raise; the dispatcher catches and returns a structured error.
"""
from __future__ import annotations

import re
from typing import Protocol

from edit_chain_schema import (
    BridgeTopLoops,
    ColorSplit,
    Decimate,
    EditChain,
    FixNormals,
    FlatBottom,
    KeepLargest,
    OpenTop,
    RecenterXY,
    ScaleToLongest,
    VoxelRemesh,
)


# ── Backend contract ─────────────────────────────────────────────────────────


class Backend(Protocol):
    """Anything that can turn a free-form user instruction into a chain.

    Every implementation must:

      - Return a fully validated :class:`EditChain` (no half-validated
        dicts). Construct via the model classes so Pydantic catches
        range and discriminator violations at construction, not at the
        far edge of the pipeline.
      - Be deterministic for testing OR accept a seed/temperature
        knob. The mock is deterministic; the llama.cpp backend will be
        seeded by default in tests.
      - Treat ``sanity`` (current mesh state) as optional context — for
        a first-edit-after-generate call, no sanity exists yet.
    """

    def generate(
        self,
        user_prompt: str,
        object_type: str = "solid_decorative",
        sanity: dict | None = None,
    ) -> EditChain: ...


# ── MockBackend: keyword routing ─────────────────────────────────────────────


# Compiled once. Looking up a number followed by mm (with or without space).
# Captures the number; we floor it to the schema's [1, 300] range.
_TARGET_MM_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*mm\b", flags=re.IGNORECASE
)
# Looks for explicit count hints near "color" / "wedge" / "band" words.
_COUNT_NEAR_COLOR_RE = re.compile(
    r"\b(\d+)\s*(?:color|colors|colour|colours|band|bands|wedge|wedges)\b",
    flags=re.IGNORECASE,
)

_VASE_KEYWORDS = ("vase", "open top", "hollow", "container", "cup", "pot")
_COLOR_SPLIT_KEYWORDS = ("color", "colour", "multicolor", "filament", "band", "zebra")
_QUARTER_KEYWORDS = ("quarter", "wedge", "wedges", "sectors", "sectored")
_FLAT_BOTTOM_KEYWORDS = ("flat bottom", "flat base", "stable", "sit flat", "flatten the base")
_LIGHT_KEYWORDS = ("light", "lighter", "less detail", "low poly", "simpler", "lower poly")
_DETAIL_KEYWORDS = ("detail", "detailed", "preserve", "high poly", "fine")
_NO_CLEAN_KEYWORDS = ("don't clean", "skip clean", "raw", "as is", "as-is")


def _matches_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(n in text for n in needles)


def _detect_target_mm(text: str, default: float) -> float:
    m = _TARGET_MM_RE.search(text)
    if not m:
        return default
    try:
        v = float(m.group(1))
    except ValueError:
        return default
    # Schema range is gt=0, le=300. Clamp silently — a sane chain is
    # better than a validation error from a user typo like "5000mm".
    return max(1.0, min(300.0, v))


def _detect_color_split_count(text: str, default: int) -> int:
    m = _COUNT_NEAR_COLOR_RE.search(text)
    if not m:
        return default
    try:
        v = int(m.group(1))
    except ValueError:
        return default
    return max(2, min(32, v))


def _decimate_target_for(text: str) -> int:
    """Pick a face-count target based on style words. Real LLM will be
    much better at this — here we just need three plausible buckets."""
    if _matches_any(text, _LIGHT_KEYWORDS):
        return 20_000
    if _matches_any(text, _DETAIL_KEYWORDS):
        return 100_000
    return 50_000  # historical default in src/lib/edits.ts DEFAULT_PARAMS


class MockBackend:
    """Keyword-routing pseudo-LLM. Deterministic; safe for unit tests
    and for letting J.3 build the UI without llama-cpp-python installed.

    Routing rules — kept simple on purpose:

      - Always emit a canonical-clean spine: scale → voxel → keep_largest
        → recenter → fix_normals → decimate.
      - ``object_type=='vase'`` or vase-ish keywords append open_top
        + bridge_top_loops.
      - Solid_decorative / flat_part get flat_bottom unless the user
        explicitly asked for no clean-up.
      - Color words append color_split. "quarter"/"wedge" means quarter
        mode; otherwise zebra.
      - Number parsing: "80mm" overrides default scale; "<N> colors"
        overrides default count.
      - Style words (light/detailed) tune the decimate target face
        count, in three buckets.

    None of this is "intelligent" — it just produces plausible chains
    that exercise every UI code path. Once llama.cpp is wired in (J.4)
    this class is left in place as the fallback / offline mode.
    """

    name = "mock-keyword-router"

    def generate(
        self,
        user_prompt: str,
        object_type: str = "solid_decorative",
        sanity: dict | None = None,
    ) -> EditChain:
        text = (user_prompt or "").lower().strip()

        target_mm = _detect_target_mm(text, default=80.0)
        skip_clean = _matches_any(text, _NO_CLEAN_KEYWORDS)
        vase_like = object_type == "vase" or _matches_any(text, _VASE_KEYWORDS)
        wants_color = _matches_any(text, _COLOR_SPLIT_KEYWORDS) or _matches_any(text, _QUARTER_KEYWORDS)
        wants_quarter = _matches_any(text, _QUARTER_KEYWORDS)

        # Solid / flat_part want a flat base by default; vases don't
        # (open_top + bridge handle the top, and a vase usually sits
        # on its own base). The user can override with explicit words.
        wants_flat_bottom = (not vase_like) and (
            not skip_clean
            or _matches_any(text, _FLAT_BOTTOM_KEYWORDS)
        )

        # Spine — canonical-clean ops every chain needs.
        edits = [
            ScaleToLongest(type="scale_to_longest", target_mm=target_mm),
            VoxelRemesh(type="voxel_remesh", voxel_mm=0.8),
            KeepLargest(type="keep_largest"),
            RecenterXY(type="recenter_xy"),
        ]
        if wants_flat_bottom:
            edits.append(FlatBottom(type="flat_bottom", cut_mm=1.0))
        edits.append(FixNormals(type="fix_normals"))
        edits.append(
            Decimate(type="decimate", target_faces=_decimate_target_for(text))
        )

        # Vase-specific: open_top + bridge.
        if vase_like:
            edits.append(OpenTop(type="open_top", cut_mm=2.0))
            edits.append(BridgeTopLoops(type="bridge_top_loops"))

        # Multi-colour split goes last (orchestrator order rule).
        if wants_color:
            mode = "quarter" if wants_quarter else "zebra"
            count = _detect_color_split_count(text, default=8)
            edits.append(ColorSplit(type="color_split", mode=mode, count=count))

        return EditChain(edits=edits)


# ── Module-level backend selection ───────────────────────────────────────────
#
# Default to the mock so the sidecar is usable even when llama-cpp-python
# isn't installed (the case for J.2 / J.3 testing, and for any deployment
# where the model file hasn't been downloaded yet). J.4 will overwrite
# this when it can successfully load a GGUF.

_backend: Backend = MockBackend()


def set_backend(backend: Backend) -> None:
    """Replace the active backend. Called by J.4 on successful model load
    and by tests that need to substitute a deterministic fixture."""
    global _backend
    _backend = backend


def get_backend() -> Backend:
    return _backend


def backend_name() -> str:
    return getattr(_backend, "name", _backend.__class__.__name__)


def generate_edit_chain(
    user_prompt: str,
    object_type: str = "solid_decorative",
    sanity: dict | None = None,
) -> EditChain:
    """Single entry point. Returns a validated chain or raises whatever
    the backend raises. The JSON-RPC dispatcher in main.py is responsible
    for catching and translating to a structured error."""
    return _backend.generate(user_prompt, object_type, sanity)
