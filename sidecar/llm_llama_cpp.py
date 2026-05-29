"""
LlamaCppBackend (Phase J.4) — real local inference via llama-cpp-python.

Lazy-import design
------------------

Every reference to llama_cpp lives *inside* a method, not at module
import time. This is deliberate:

  * llama-cpp-python triggers loading native DLLs on import. If even
    one DLL is missing the import raises, and any module that
    transitively `import`ed this file would also fail.
  * llama-cpp-python has no pre-built wheels for Python 3.14 (as of
    May 2026); installs build from source. Many dev / CI environments
    won't have it. The sidecar must remain runnable without it — the
    AI Editor stays on the J.2 mock when this backend is absent or
    can't load.
  * Tests can swap the lazy loader for a fake without monkey-patching
    a real module import.

So this file can be `import llm_llama_cpp` from anywhere, and only the
explicit call to ``LlamaCppBackend(model_path=...).warm_up()`` (or the
first ``.generate(...)``) reaches into llama_cpp territory. If the
import fails there, the caller catches and falls back to mock.

The grammar from llm_grammar.gbnf is loaded once per backend instance
and reused for every sample — llama-cpp-python's LlamaGrammar caches
the parsed automaton, so reloading per request would be wasted work.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from edit_chain_schema import EditChain, validate_chain
from llm_prompts import build_messages

logger = logging.getLogger(__name__)


# Canonical filename for the default model. Matches the J.5 download
# target; kept in this file so the install logic can use it without
# importing the eventual download module.
DEFAULT_MODEL_FILENAME = "qwen2.5-coder-7b-instruct-q4_k_m.gguf"

# Default sampler parameters tuned for this task:
#   - temperature 0.2: NL→structured-output benefits from low randomness
#   - max_tokens 1024: a 10-op chain is ~400 tokens of JSON; 1024 is
#     plenty even with whitespace and slight overshoot
#   - n_ctx 4096: system prompt is ~1500 tokens, user prompt + output
#     well under 2k more
#   - n_threads None means llama-cpp-python picks based on CPU count
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 1024
DEFAULT_N_CTX = 4096


def default_model_dir() -> Path:
    """Where the J.5 downloader will (eventually) write GGUFs and where
    we look at startup. Per CHAT_RESUME / project conventions: under
    LOCALAPPDATA, sibling to projects/ and logs/."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / "Conjure3D" / "models"


def default_model_path() -> Path:
    return default_model_dir() / DEFAULT_MODEL_FILENAME


def grammar_path() -> Path:
    """The GBNF file lives next to this script (or in PyInstaller's
    _MEIPASS bundle). See scripts/build-sidecar.ps1 — we --add-data it
    explicitly into the onefile bundle."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "llm_grammar.gbnf"
    return Path(__file__).parent / "llm_grammar.gbnf"


class LlamaBackendUnavailable(RuntimeError):
    """Raised when the backend can't be set up — missing library,
    missing model, GPU-driver failure, etc. The install function
    catches and stays on the mock; the AI Editor surfaces the
    structured error_code 'backend_error'."""


class LlamaCppBackend:
    """Real-LLM backend. Mirrors the Backend protocol in llm.py."""

    name = "llama-cpp-qwen2.5-coder"

    def __init__(
        self,
        model_path: str | Path,
        grammar_path: str | Path | None = None,
        n_ctx: int = DEFAULT_N_CTX,
        n_threads: int | None = None,
        n_gpu_layers: int = 0,  # CPU-only by default; GPU is a v1.1 toggle
        verbose: bool = False,
    ):
        self.model_path = Path(model_path)
        self.grammar_path = Path(grammar_path) if grammar_path else None
        self.n_ctx = n_ctx
        self.n_threads = n_threads
        self.n_gpu_layers = n_gpu_layers
        self.verbose = verbose
        # Filled in by warm_up(). Kept as Any because llama_cpp may not
        # be importable at type-check time on dev machines without it.
        self._llama: Any | None = None
        self._grammar: Any | None = None

    # ── Public ──────────────────────────────────────────────────────────────

    def warm_up(self) -> None:
        """Eagerly load model + grammar so the first .generate() call
        isn't slow. Safe to call multiple times. Raises
        LlamaBackendUnavailable on any failure."""
        if self._llama is not None:
            return
        if not self.model_path.is_file():
            raise LlamaBackendUnavailable(
                f"Model file not found at {self.model_path}. "
                "Download it from the Settings screen (Phase J.5)."
            )
        try:
            from llama_cpp import Llama, LlamaGrammar  # noqa: WPS433 (lazy import)
        except ImportError as exc:
            raise LlamaBackendUnavailable(
                f"llama-cpp-python is not installed: {exc}. "
                "Install it or run the AI Editor in mock mode."
            ) from exc

        try:
            self._llama = Llama(
                model_path=str(self.model_path),
                n_ctx=self.n_ctx,
                n_threads=self.n_threads,
                n_gpu_layers=self.n_gpu_layers,
                verbose=self.verbose,
            )
        except Exception as exc:  # noqa: BLE001
            raise LlamaBackendUnavailable(
                f"Failed to load model {self.model_path}: {exc}"
            ) from exc

        if self.grammar_path is not None:
            try:
                grammar_text = self.grammar_path.read_text(encoding="utf-8")
                self._grammar = LlamaGrammar.from_string(grammar_text)
            except Exception as exc:  # noqa: BLE001
                raise LlamaBackendUnavailable(
                    f"Failed to load grammar {self.grammar_path}: {exc}"
                ) from exc

    def generate(
        self,
        user_prompt: str,
        object_type: str = "solid_decorative",
        sanity: dict[str, Any] | None = None,
    ) -> EditChain:
        """Sample one edit chain. Lazily warms up if not yet loaded."""
        self.warm_up()
        assert self._llama is not None  # narrowed by warm_up()

        messages = build_messages(user_prompt, object_type, sanity)

        # Sample. GBNF constrains every token to keep output valid;
        # temperature controls how "creative" the model is within those
        # constraints (low for structured output, higher for prose).
        completion = self._llama.create_chat_completion(
            messages=messages,
            grammar=self._grammar,
            max_tokens=DEFAULT_MAX_TOKENS,
            temperature=DEFAULT_TEMPERATURE,
        )

        # Defensive: the OpenAI-style response shape llama-cpp-python
        # returns can vary slightly across versions; pluck content
        # carefully and produce a clear error if missing.
        try:
            content = completion["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LlamaBackendUnavailable(
                f"Unexpected llama-cpp-python response shape: {completion!r}"
            ) from exc

        # The grammar guarantees valid JSON. Validate the SHAPE through
        # Pydantic — defence in depth against grammar drift and range
        # violations the grammar doesn't enforce (e.g. target_mm = -5).
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:  # should be impossible w/ grammar
            raise LlamaBackendUnavailable(
                f"LLM returned non-JSON despite GBNF constraint: {content!r}"
            ) from exc

        return validate_chain(data)


# ── Probe helpers (used by llm.try_install_llama_backend) ───────────────────


def llama_cpp_importable() -> bool:
    """Cheap probe: can we import llama_cpp without crashing? Catches
    both ImportError (not installed) and OSError (DLL not found on
    Windows when partial installs leave .pyd without runtime DLLs)."""
    try:
        import llama_cpp  # noqa: F401
        return True
    except Exception:  # noqa: BLE001 — any failure means "no"
        return False


def find_model_path(override: str | os.PathLike | None = None) -> Path | None:
    """Locate the GGUF file. Override path wins; otherwise check the
    canonical default. Returns None if nothing is on disk."""
    if override is not None:
        p = Path(override)
        return p if p.is_file() else None
    p = default_model_path()
    return p if p.is_file() else None
