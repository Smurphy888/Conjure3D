"""
Tripo AI client for text-to-3D generation. Mirrors meshy.py's command
surface (generate_preview / poll_task / download_glb) so the model.*
routing layer in main.py can swap providers without touching the frontend.

Contract notes:
- API key lives in Windows Credential Manager (service "conjure3d",
  account "tripo_api_key"). Never logged.
- Tripo is single-shot — no preview→refine two-phase flow. generate_preview
  submits the task; poll_task checks progress; download_glb fetches the GLB.
- Status is normalised to "PROCESSING" | "SUCCEEDED" | "FAILED" to match
  the existing Generate.tsx polling contract (established by meshy.py).
- Errors are surfaced verbatim. No auto-retry (Tripo charges credits per
  generation, same policy as Meshy).
- requests is imported lazily inside functions so the sidecar module graph
  stays resilient to import failures in minimal environments.
"""
import os

import keyring

_KEYRING_SERVICE = "conjure3d"
_KEYRING_ACCOUNT = "tripo_api_key"

API_BASE = "https://api.tripo3d.ai/v2/openapi/task"

_TIMEOUT = (10, 120)
_DOWNLOAD_CHUNK = 64 * 1024

# Tripo status vocab (lowercase from API) → normalised contract
_STATUS_MAP: dict[str, str] = {
    "queued": "PROCESSING",
    "submitted": "PROCESSING",
    "processing": "PROCESSING",
    "success": "SUCCEEDED",
    "failed": "FAILED",
    "cancelled": "FAILED",
}


class TripoError(RuntimeError):
    """Raised with the verbatim API/transport error text. No retry."""


def _api_key() -> str:
    key = keyring.get_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT)
    if not key:
        raise TripoError(
            "No Tripo AI API key set. Add it in Settings "
            "(stored in Windows Credential Manager)."
        )
    return key


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }


def generate_preview(params: dict) -> dict:
    """POST a text_to_model task. params: {prompt, negative_prompt?}.
    Returns {task_id}."""
    import requests

    payload: dict = {
        "type": "text_to_model",
        "prompt": params["prompt"],
    }
    if params.get("negative_prompt"):
        payload["negative_prompt"] = params["negative_prompt"]

    try:
        resp = requests.post(
            API_BASE, json=payload, headers=_headers(), timeout=_TIMEOUT
        )
    except requests.exceptions.RequestException as exc:
        raise TripoError(str(exc)) from exc
    if not resp.ok:
        raise TripoError(resp.text)
    body = resp.json()
    if body.get("code") != 0:
        raise TripoError(body.get("message") or resp.text)
    return {"task_id": body["data"]["task_id"]}


def poll_task(params: dict) -> dict:
    """GET /task/{task_id}. Single-shot. Normalises Tripo status to
    "PROCESSING" | "SUCCEEDED" | "FAILED". On success, GLB URL is at
    data.output.pbr_model (preferred) or data.output.model."""
    import requests

    task_id = params["task_id"]
    try:
        resp = requests.get(
            f"{API_BASE}/{task_id}", headers=_headers(), timeout=_TIMEOUT
        )
    except requests.exceptions.RequestException as exc:
        raise TripoError(str(exc)) from exc
    if not resp.ok:
        raise TripoError(resp.text)

    body = resp.json()
    if body.get("code") != 0:
        raise TripoError(body.get("message") or resp.text)

    data = body.get("data", {})
    raw = (data.get("status") or "").lower()
    progress = int(data.get("progress") or 0)
    normalised = _STATUS_MAP.get(raw, "PROCESSING")

    if normalised == "SUCCEEDED":
        output = data.get("output") or {}
        glb_url = output.get("pbr_model") or output.get("model") or ""
        return {
            "status": "SUCCEEDED",
            "progress": 100,
            "model_urls": {"glb": glb_url},
        }
    if normalised == "FAILED":
        return {
            "status": "FAILED",
            "progress": progress,
            "task_error": data.get("message") or "Tripo AI generation failed.",
        }
    return {"status": "PROCESSING", "progress": progress}


def download_glb(params: dict) -> dict:
    """Stream a Tripo GLB to disk and verify its size.
    params: {url, dest}. Returns {path, bytes}."""
    import requests

    url = params["url"]
    dest = params["dest"]
    tmp = f"{dest}.part"

    try:
        with requests.get(url, stream=True, timeout=_TIMEOUT) as resp:
            if not resp.ok:
                raise TripoError(resp.text)
            expected = resp.headers.get("Content-Length")
            written = 0
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=_DOWNLOAD_CHUNK):
                    if chunk:
                        fh.write(chunk)
                        written += len(chunk)
    except requests.exceptions.RequestException as exc:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise TripoError(str(exc)) from exc

    if expected is not None and int(expected) != written:
        os.remove(tmp)
        raise TripoError(
            f"Download size mismatch: expected {expected} bytes, got {written}"
        )
    if written == 0:
        os.remove(tmp)
        raise TripoError("Download produced an empty file")

    os.replace(tmp, dest)
    return {"path": dest, "bytes": written}
