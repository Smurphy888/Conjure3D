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

import keyring

from edit_chain_schema import EditChain, validate_chain
from llm_prompts import build_messages

_KEYRING_SERVICE = "conjure3d"
_OPENROUTER_KEYRING_ACCOUNT = "openrouter_api_key"

_API_URL = "https://openrouter.ai/api/v1/chat/completions"
_VALIDATE_URL = "https://openrouter.ai/api/v1/auth/key"

# Default model — a capable NON-ANTHROPIC coder, consistent with the local
# Qwen2.5-Coder so prompt behaviour is familiar. User-overridable, except
# Anthropic models are rejected outright (see __init__).
DEFAULT_MODEL = "qwen/qwen-2.5-coder-32b-instruct"

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


def _to_chain_dict(text: str) -> dict:
    """Extract + sanitise the JSON object from a model reply.

    Cloud models (no GBNF grammar) produce several common mis-shapes that we
    recover from before handing to validate_chain:

      1. Correct shape — pass through (strip stray root fields):
           {"type":"X","target_mm":200,"edits":[...]}  →  {"edits":[...]}

      2. Single edit without the array wrapper:
           {"type":"scale_to_longest","target_mm":150}  →  {"edits":[that dict]}

      3. Alternative key names (operations, chain, steps):
           {"operations":[...]}  →  {"edits":[...]}

    Raises ValueError on any parse or structural failure so the generate()
    retry loop feeds the error back to the model and tries once more.
    """
    import json

    raw = _extract_json_object(text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model reply is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Model returned a non-object JSON value")

    # Case 1 / stray-root-field variant: has "edits" key → isolate it.
    if "edits" in data:
        return {"edits": data["edits"]}

    # Case 2: model returned a single edit dict without the array wrapper.
    # Detect by presence of "type" (the discriminator field every op has).
    if "type" in data:
        return {"edits": [data]}

    # Case 3: model used an alternative collection key.
    for alt in ("operations", "chain", "steps"):
        if alt in data and isinstance(data[alt], list):
            return {"edits": data[alt]}

    raise ValueError(
        "JSON object has no 'edits' key and doesn't look like a single edit op"
    )


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
