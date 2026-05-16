"""
Real Meshy API client (Phase F Issue #23). Mirrors the meshy_mock command
surface so it is a drop-in replacement: ``generate_preview``, ``poll_task``,
``refine`` plus ``download_glb``. main.py keeps importing meshy_mock by
default; the user swaps the import for live API acceptance (see HANDOFF.md /
the Phase F gate).

Contract notes:
- API key lives in Windows Credential Manager (service ``conjure3d``,
  account ``meshy_api_key``). Never logged.
- Errors are surfaced verbatim. The HTTP response body / exception text is
  raised as MeshyError with no modification and NO auto-retry — Meshy charges
  credits per call, so a silent retry would double-spend (pipeline.md).
- ``poll_task`` is single-shot: the frontend drives the poll interval. The
  10 s / 5 min cadence from pipeline.md is exposed as module constants for
  any server-side caller but no blocking wait loop is built (it would freeze
  the single-threaded stdio sidecar).
- ``requests`` is imported lazily so the sidecar still loads in minimal
  environments where the dep is absent.
- Status is normalised to the frontend's mock-era contract
  ("PROCESSING" | "SUCCEEDED" | "FAILED") so the existing Generate screen
  works unchanged.
"""
import os

import keyring

_KEYRING_SERVICE = "conjure3d"
_KEYRING_ACCOUNT = "meshy_api_key"

API_BASE = "https://api.meshy.ai/openapi/v2/text-to-3d"

# pipeline.md § Phase 2: poll every 10 s, give up after 5 min. Exposed for
# callers that drive their own loop; this module never blocks on it.
POLL_INTERVAL_S = 10
POLL_CAP_S = 300

# (connect timeout, read timeout) seconds — keeps the stdio sidecar from
# hanging forever if Meshy stalls.
_TIMEOUT = (10, 120)
_DOWNLOAD_CHUNK = 64 * 1024


class MeshyError(RuntimeError):
    """Raised with the verbatim API/transport error text. No retry."""


def _api_key() -> str:
    key = keyring.get_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT)
    if not key:
        raise MeshyError(
            "No Meshy API key set. Add it in Settings "
            "(stored in Windows Credential Manager)."
        )
    return key


def _headers() -> dict:
    return {"Authorization": f"Bearer {_api_key()}"}


def _post(payload: dict) -> dict:
    import requests  # lazy: keeps module import resilient

    try:
        resp = requests.post(
            API_BASE, json=payload, headers=_headers(), timeout=_TIMEOUT
        )
    except requests.exceptions.RequestException as exc:
        raise MeshyError(str(exc)) from exc  # verbatim transport error
    if not resp.ok:
        raise MeshyError(resp.text)  # verbatim API error body, no retry
    return resp.json()


def _get(task_id: str) -> dict:
    import requests

    try:
        resp = requests.get(
            f"{API_BASE}/{task_id}", headers=_headers(), timeout=_TIMEOUT
        )
    except requests.exceptions.RequestException as exc:
        raise MeshyError(str(exc)) from exc
    if not resp.ok:
        raise MeshyError(resp.text)
    return resp.json()


def generate_preview(params: dict) -> dict:
    """POST mode=preview. params: {prompt, art_style?, negative_prompt?}."""
    payload = {
        "mode": "preview",
        "prompt": params["prompt"],
        "art_style": params.get("art_style", "realistic"),
    }
    if params.get("negative_prompt"):
        payload["negative_prompt"] = params["negative_prompt"]
    data = _post(payload)
    return {"task_id": data["result"]}


def refine(params: dict) -> dict:
    """POST mode=refine. params: {preview_task_id}."""
    data = _post({
        "mode": "refine",
        "preview_task_id": params["preview_task_id"],
    })
    return {"task_id": data["result"]}


def poll_task(params: dict) -> dict:
    """
    GET /{task_id}. Single-shot. Normalises Meshy's status vocabulary to the
    frontend's ("PROCESSING" | "SUCCEEDED" | "FAILED"). On a failed task the
    verbatim Meshy error message is passed through as ``task_error``.
    """
    data = _get(params["task_id"])
    raw = (data.get("status") or "").upper()
    progress = int(data.get("progress") or 0)

    if raw == "SUCCEEDED":
        model_urls = data.get("model_urls") or {}
        return {
            "status": "SUCCEEDED",
            "progress": 100,
            "model_urls": {"glb": model_urls.get("glb", "")},
        }
    if raw in ("FAILED", "CANCELED", "EXPIRED"):
        task_error = data.get("task_error") or {}
        return {
            "status": "FAILED",
            "progress": progress,
            "task_error": task_error.get("message", "") or str(task_error),
        }
    # PENDING / IN_PROGRESS / anything non-terminal
    return {"status": "PROCESSING", "progress": progress}


def download_glb(params: dict) -> dict:
    """
    Stream a Meshy GLB to disk and verify its size. Meshy's signed S3 URLs
    expire (~24 h) so the GLB must be downloaded once and the local path
    stored (HANDOFF.md). params: {url, dest}. Returns {path, bytes}.
    """
    import requests

    url = params["url"]
    dest = params["dest"]
    tmp = f"{dest}.part"

    try:
        with requests.get(url, stream=True, timeout=_TIMEOUT) as resp:
            if not resp.ok:
                raise MeshyError(resp.text)
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
        raise MeshyError(str(exc)) from exc  # verbatim (e.g. hosts-blocked)

    if expected is not None and int(expected) != written:
        os.remove(tmp)
        raise MeshyError(
            f"Download size mismatch: expected {expected} bytes, "
            f"got {written}"
        )
    if written == 0:
        os.remove(tmp)
        raise MeshyError("Download produced an empty file")

    os.replace(tmp, dest)  # atomic
    return {"path": dest, "bytes": written}
