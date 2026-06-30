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
