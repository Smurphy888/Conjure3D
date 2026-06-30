"""
OpenAI LLM backend (cloud provider, sibling of llm_openrouter).

Same OpenAI-compatible chat-completions wire protocol as the OpenRouter
backend — they differ only in base URL, default model, keyring account, and
the validate endpoint. (Follow-up worth doing: factor the shared
_extract_json_object + generate-retry loop into one base both subclass. Kept
mirrored for now to avoid churning the committed+tested OpenRouter path.)

Key in Windows Credential Manager (service ``conjure3d``, account
``openai_api_key``). Never logged.
"""
from __future__ import annotations

import re
import sys

import keyring

from edit_chain_schema import EditChain, validate_chain
from llm_prompts import build_messages

_KEYRING_SERVICE = "conjure3d"
_OPENAI_KEYRING_ACCOUNT = "openai_api_key"

_API_URL = "https://api.openai.com/v1/chat/completions"
_VALIDATE_URL = "https://api.openai.com/v1/models"

# Non-Anthropic default. gpt-4o-mini is cheap, fast, and good enough at
# emitting the small JSON edit chain.
DEFAULT_MODEL = "gpt-4o-mini"

_TIMEOUT = (10, 120)


class OpenAIError(RuntimeError):
    """Raised with a verbatim transport/API error body (never the key)."""


def set_openai_key(key: str) -> None:
    keyring.set_password(_KEYRING_SERVICE, _OPENAI_KEYRING_ACCOUNT, key)


def has_openai_key() -> bool:
    return bool(keyring.get_password(_KEYRING_SERVICE, _OPENAI_KEYRING_ACCOUNT))


def _extract_json_object(text: str) -> str:
    """First balanced ``{...}`` object, after stripping markdown fences."""
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


class OpenAIBackend:
    """Cloud Backend talking directly to api.openai.com."""

    def __init__(self, model: str | None = None, api_key: str | None = None):
        self.model = model or DEFAULT_MODEL
        self._api_key_override = api_key

    @property
    def name(self) -> str:
        return f"openai:{self.model}"

    @property
    def _api_key(self) -> str:
        if self._api_key_override:
            return self._api_key_override
        key = keyring.get_password(_KEYRING_SERVICE, _OPENAI_KEYRING_ACCOUNT)
        if not key:
            raise OpenAIError(
                "No OpenAI API key set. Add it in Settings "
                "(stored in Windows Credential Manager)."
            )
        return key

    def warm_up(self) -> None:
        _ = self._api_key

    def validate(self) -> None:
        """Live key check that GATES a provider switch. Free + fast; tells a
        rejected key (401/403) apart from a network failure."""
        import requests

        try:
            resp = requests.get(
                _VALIDATE_URL, headers=self._headers(), timeout=(10, 15)
            )
        except requests.exceptions.RequestException as exc:
            raise OpenAIError(f"Couldn't reach OpenAI: {exc}") from exc
        if resp.status_code in (401, 403):
            raise OpenAIError(
                f"OpenAI rejected the API key (HTTP {resp.status_code}). "
                "Check the key (it should start with sk-)."
            )
        if not resp.ok:
            raise OpenAIError(
                f"OpenAI key check failed (HTTP {resp.status_code}): "
                f"{resp.text[:200]}"
            )

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _chat(self, messages: list[dict]) -> str:
        import requests

        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            # OpenAI honours json_object as long as "json" appears in the
            # messages — build_system_message() says JSON repeatedly, so we're
            # covered; the drop-on-400 fallback below backstops it anyway.
            "response_format": {"type": "json_object"},
        }
        try:
            resp = requests.post(
                _API_URL, json=body, headers=self._headers(), timeout=_TIMEOUT
            )
        except requests.exceptions.RequestException as exc:
            raise OpenAIError(str(exc)) from exc

        if resp.status_code == 400 and "response_format" in (resp.text or ""):
            body.pop("response_format", None)
            try:
                resp = requests.post(
                    _API_URL, json=body, headers=self._headers(), timeout=_TIMEOUT
                )
            except requests.exceptions.RequestException as exc:
                raise OpenAIError(str(exc)) from exc

        if not resp.ok:
            raise OpenAIError(f"OpenAI API error {resp.status_code}: {resp.text}")
        try:
            return resp.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise OpenAIError(f"Unexpected OpenAI response shape: {exc}") from exc

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
                f"[openai] attempt {attempt + 1} raw reply: {content!r}",
                file=sys.stderr,
                flush=True,
            )
            try:
                return validate_chain(_to_chain_dict(content))
            except Exception as exc:
                last_err = exc
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

        raise OpenAIError(
            f"OpenAI returned an invalid edit chain after a retry: {last_err}"
        )
