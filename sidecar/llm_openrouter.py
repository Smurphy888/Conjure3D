"""
OpenRouter LLM backend (Phase J.6 — cloud escape hatch).

This is the cloud fallback for machines where the local llama.cpp model can't
run (e.g. a CPU without the AVX level the bundled engine needs). It implements
the same ``Backend`` protocol as MockBackend / LlamaCppBackend in llm.py, so
the dispatcher and UI are unchanged — only the chain *generation* moves to a
remote model.

Key differences from the local path:

  * NO GBNF grammar. OpenRouter is an OpenAI-compatible chat endpoint with no
    token-level grammar constraint, so the model CAN return prose, markdown
    fences, or a malformed object despite the prompt. We therefore: request
    JSON output (best-effort), strip fences + extract the first balanced JSON
    object, validate through the Pydantic schema, and on failure retry ONCE
    with the validation error fed back as a corrective turn. The same Pydantic
    schema that backstops the local path is the real safety net here.

  * Non-Anthropic only. Project rule: the shipped product must not spend
    Anthropic tokens. The default model is a non-Anthropic coder model and the
    constructor HARD-REJECTS any ``anthropic/*`` model id as defence in depth,
    even if a user tries to set one.

  * API key in Windows Credential Manager (service ``conjure3d``, account
    ``openrouter_api_key``). Never logged — request headers are never printed,
    and surfaced errors are response *bodies* (which never contain the key).
"""
from __future__ import annotations

import re
import sys

import keyring

from edit_chain_schema import EditChain, validate_chain
from llm_prompts import build_messages

_KEYRING_SERVICE = "conjure3d"
_OPENROUTER_KEYRING_ACCOUNT = "openrouter_api_key"

_API_URL = "https://openrouter.ai/api/v1/chat/completions"
_VALIDATE_URL = "https://openrouter.ai/api/v1/auth/key"

# Default model — Qwen2.5-72B-Instruct. NON-ANTHROPIC, same family as the
# local Qwen2.5-Coder so prompt behaviour is familiar. User-overridable,
# except Anthropic models are rejected outright (see __init__).
#
# We deliberately do NOT use qwen-2.5-coder-32b-instruct: as served on
# OpenRouter it DETERMINISTICALLY emits malformed-quote JSON for simple
# requests — e.g. `{"edits:[{type":"scale_to_longest","target_mm":256}` — which
# json.loads happily parses into a junk-keyed dict, so no post-parse repair can
# recover it (verified live 2026-06-30, 4/4 identical at temp 0.2). The 72B
# instruct variant returned clean {"edits":[...]} across scale / bisect / full
# vase chains (6/6). llama-3.3-70b was rejected too: it fell into a degenerate
# repetition loop on "split in half".
DEFAULT_MODEL = "qwen/qwen-2.5-72b-instruct"

# (connect, read) timeouts — keep the stdio sidecar from hanging on a stall.
_TIMEOUT = (10, 120)


class OpenRouterError(RuntimeError):
    """Raised with a verbatim transport/API error body (never the key)."""


def set_openrouter_key(key: str) -> None:
    keyring.set_password(_KEYRING_SERVICE, _OPENROUTER_KEYRING_ACCOUNT, key)


def has_openrouter_key() -> bool:
    val = keyring.get_password(_KEYRING_SERVICE, _OPENROUTER_KEYRING_ACCOUNT)
    return bool(val)


def _extract_json_object(text: str) -> str:
    """Pull the first balanced ``{...}`` object out of a model reply, after
    stripping markdown code fences. Raises ValueError if none is found — the
    caller treats that like a validation failure and retries."""
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s).strip()

    start = s.find("{")
    if start == -1:
        raise ValueError("model output contained no JSON object")

    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    raise ValueError("model output had an unbalanced JSON object")


# Collection keys a cloud model might use instead of "edits", in priority
# order. The first one whose value is a list wins.
_COLLECTION_KEYS = ("edits", "operations", "chain", "steps", "ops", "actions", "plan")


def _recover_edits(data, _depth: int = 0):
    """Return the edits *list* from a parsed model reply, or None if it can't
    be recovered. General by design — handles arbitrary collection-key names,
    a bare single edit, a top-level array, and one or more levels of object
    nesting ({"edit_chain": {"edits": [...]}}).

    It deliberately does NOT fabricate an edit from ambiguous data such as
    op-name-as-key ({"scale_to_longest": {...}}) or bare params
    ({"target_mm": 200}): silently applying a guessed geometry op is worse
    than a clean, visible failure the user can rephrase.
    """
    if _depth > 4:
        return None
    # A bare list at the root already IS the edits array.
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return None
    # Known collection key with a list value.
    for key in _COLLECTION_KEYS:
        if isinstance(data.get(key), list):
            return data[key]
    # The dict is itself one edit (carries the discriminator field).
    if "type" in data:
        return [data]
    # Any value that's a non-empty list of edit-shaped dicts, under any key.
    for val in data.values():
        if (
            isinstance(val, list)
            and val
            and all(isinstance(x, dict) and "type" in x for x in val)
        ):
            return val
    # Single-key wrapper, e.g. {"response": {...}} / {"edit_chain": {...}} —
    # unwrap one level and recurse.
    if len(data) == 1:
        only = next(iter(data.values()))
        if isinstance(only, (dict, list)):
            return _recover_edits(only, _depth + 1)
    return None


def _to_chain_dict(text: str) -> dict:
    """Extract + sanitise the JSON object from a model reply into
    {"edits": [...]} ready for validate_chain.

    Cloud models (no GBNF grammar) wrap the list under varying keys, drop the
    array wrapper for a single op, or nest the whole thing one level deep;
    _recover_edits absorbs all of those. On an unrecoverable reply we raise a
    ValueError that INCLUDES the offending shape (top-level keys + a truncated
    raw dump) so the failure is self-diagnosing from the UI/log instead of an
    opaque "no edits key" — and so the generate() retry loop can feed it back.
    """
    import json

    raw = _extract_json_object(text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Model reply is not valid JSON: {exc}. Raw: {raw[:200]}"
        ) from exc

    edits = _recover_edits(data)
    if edits is None:
        keys = sorted(data.keys()) if isinstance(data, dict) else "(not an object)"
        raise ValueError(
            f"Could not find an edits array in the model reply "
            f"(top-level keys: {keys}; raw: {raw[:200]})"
        )
    return {"edits": edits}


class OpenRouterBackend:
    """Cloud Backend. ``generate`` returns a validated EditChain or raises
    OpenRouterError (transport) / the last ValidationError-derived message
    after one corrective retry."""

    def __init__(self, model: str | None = None, api_key: str | None = None):
        self.model = model or DEFAULT_MODEL
        if self.model.lower().startswith("anthropic/"):
            raise OpenRouterError(
                "Conjure3D will not route to Anthropic models on OpenRouter. "
                "Choose a non-Anthropic model."
            )
        self._api_key_override = api_key

    @property
    def name(self) -> str:
        return f"openrouter:{self.model}"

    @property
    def _api_key(self) -> str:
        if self._api_key_override:
            return self._api_key_override
        key = keyring.get_password(_KEYRING_SERVICE, _OPENROUTER_KEYRING_ACCOUNT)
        if not key:
            raise OpenRouterError(
                "No OpenRouter API key set. Add it in the AI Editor "
                "(stored in Windows Credential Manager)."
            )
        return key

    def warm_up(self) -> None:
        """Cheap readiness check used at startup — verifies a key is present
        WITHOUT spending a token. Raises OpenRouterError if missing so the
        caller leaves the mock in place and surfaces the reason."""
        _ = self._api_key

    def validate(self) -> None:
        """LIVE key check used to GATE a provider switch — confirms OpenRouter
        accepts the key before we make it the active backend. Free (no token
        spend) and fast (short timeout). Distinguishes a rejected key (401/403)
        from a network failure so the UI can show the right fix. Raises
        OpenRouterError on any problem; returns None on success."""
        import requests

        try:
            resp = requests.get(
                _VALIDATE_URL, headers=self._headers(), timeout=(10, 15)
            )
        except requests.exceptions.RequestException as exc:
            raise OpenRouterError(f"Couldn't reach OpenRouter: {exc}") from exc
        if resp.status_code in (401, 403):
            raise OpenRouterError(
                f"OpenRouter rejected the API key (HTTP {resp.status_code}). "
                "Make sure it's an OpenRouter key (starts with sk-or-v1-)."
            )
        if not resp.ok:
            raise OpenRouterError(
                f"OpenRouter key check failed (HTTP {resp.status_code}): "
                f"{resp.text[:200]}"
            )

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://conjure3d.app",
            "X-Title": "Conjure3D",
        }

    def _chat(self, messages: list[dict]) -> str:
        import requests  # lazy, like meshy.py

        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            # Best-effort JSON hint — not every model honours it, so it's a
            # hint, not a guarantee; _extract_json_object is the real guard.
            "response_format": {"type": "json_object"},
        }
        try:
            resp = requests.post(
                _API_URL, json=body, headers=self._headers(), timeout=_TIMEOUT
            )
        except requests.exceptions.RequestException as exc:
            raise OpenRouterError(str(exc)) from exc

        # Some models 400 on an unsupported response_format — drop it and retry
        # the request once without the hint rather than failing the whole call.
        if resp.status_code == 400 and "response_format" in (resp.text or ""):
            body.pop("response_format", None)
            try:
                resp = requests.post(
                    _API_URL, json=body, headers=self._headers(), timeout=_TIMEOUT
                )
            except requests.exceptions.RequestException as exc:
                raise OpenRouterError(str(exc)) from exc

        if not resp.ok:
            raise OpenRouterError(
                f"OpenRouter API error {resp.status_code}: {resp.text}"
            )
        try:
            return resp.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise OpenRouterError(
                f"Unexpected OpenRouter response shape: {exc}"
            ) from exc

    def generate(
        self,
        user_prompt: str,
        object_type: str = "solid_decorative",
        sanity: dict | None = None,
    ) -> EditChain:
        messages = build_messages(user_prompt, object_type, sanity)
        last_err: Exception | None = None

        for attempt in range(2):
            content = self._chat(messages)
            # Log the raw reply (model output, never the key) so any future
            # mis-shape is diagnosable from the session log without a repro.
            print(
                f"[openrouter] attempt {attempt + 1} raw reply: {content!r}",
                file=sys.stderr,
                flush=True,
            )
            try:
                return validate_chain(_to_chain_dict(content))
            except Exception as exc:  # ValidationError / ValueError / JSON error
                last_err = exc
                # Feed the failure back as a corrective turn and try once more.
                messages = messages + [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            f"That response was not a valid edit chain: {exc}. "
                            "Re-emit ONLY the JSON object {\"edits\":[...]} with "
                            "valid ops and in-range values. No prose, no fences."
                        ),
                    },
                ]

        raise OpenRouterError(
            f"OpenRouter returned an invalid edit chain after a retry: {last_err}"
        )
