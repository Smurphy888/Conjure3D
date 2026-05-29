"""
JSON-RPC 2.0 sidecar — stdin/stdout, newline-delimited.
All diagnostic output goes to stderr; stdout is the protocol channel only.
"""
import json
import sys
import traceback
import webbrowser

import keyring

from slugify import slugify as _slugify
from settings import read_settings, write_settings
from blender import detect_blender
from addon import install_addon
from connection import test_socket as _test_socket
from bambu import detect_bambu as _detect_bambu
import meshy as _meshy  # REAL Meshy API (Phase F accepted by user 2026-05-18; spends credits)
import orchestrator as _orchestrator  # real ops chain (Phase E #22)
import slicer as _slicer  # Bambu Studio hand-off (Phase G #25)
import project as _project  # .conjure3d.json save/load (Phase H #26)
import llm as _llm  # NL editor (Phase J.2 — mocked backend; J.4 swaps to llama.cpp)
from pydantic import ValidationError as _PydanticValidationError

_KEYRING_SERVICE = "conjure3d"
_KEYRING_ACCOUNT = "meshy_api_key"

COMMANDS = {}


def register(name):
    def decorator(fn):
        COMMANDS[name] = fn
        return fn
    return decorator


@register("system.ping")
def system_ping(params):
    return {"ok": True, "msg": "pong"}


@register("util.slugify")
def util_slugify(params):
    return {"slug": _slugify(params["name"])}


@register("settings.read")
def settings_read(_params):
    return read_settings()


@register("settings.write")
def settings_write(params):
    write_settings(params["settings"])
    return {"ok": True}


@register("wizard.detect_blender")
def wizard_detect_blender(_params):
    return detect_blender()


@register("wizard.install_addon")
def wizard_install_addon(params):
    return install_addon(params["blender_version"])


@register("wizard.test_socket")
def wizard_test_socket(_params):
    return _test_socket()


@register("wizard.detect_bambu")
def wizard_detect_bambu(_params):
    return _detect_bambu()


@register("system.set_meshy_key")
def system_set_meshy_key(params):
    key = params["key"]
    keyring.set_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT, key)
    return {"ok": True}


@register("system.has_meshy_key")
def system_has_meshy_key(_params):
    val = keyring.get_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT)
    return {"set": val is not None and val != ""}


@register("system.open_url")
def system_open_url(params):
    webbrowser.open(params["url"])
    return {"ok": True}


@register("meshy.generate_preview")
def meshy_generate_preview(params):
    return _meshy.generate_preview(params)


@register("meshy.poll_task")
def meshy_poll_task(params):
    return _meshy.poll_task(params)


@register("meshy.refine")
def meshy_refine(params):
    return _meshy.refine(params)


@register("meshy.set_fixture")
def meshy_set_fixture(params):
    # Mock-only (dev fixture toggle). Real meshy.py has no set_fixture; guard
    # so a stray call can't AttributeError now that real Meshy is wired.
    fn = getattr(_meshy, "set_fixture", None)
    if fn is None:
        return {"ok": False, "error": "set_fixture unavailable (real Meshy active)"}
    return fn(params)


@register("meshy.download_glb")
def meshy_download_glb(params):
    # Real Meshy returns a signed S3 URL that expires (~24h) and that the
    # webview cannot render directly. Fetch once to a real, writable project
    # dir derived from the project name (frontend never builds Windows paths).
    import os
    from pathlib import Path
    from slugify import slugify

    slug = slugify(params.get("name") or "model")
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Conjure3D" / "projects" / slug
    base.mkdir(parents=True, exist_ok=True)
    dest = str(base / f"{slug}.glb")
    return _meshy.download_glb({"url": params["url"], "dest": dest})


@register("edit.apply_chain")
def edit_apply_chain(params):
    return _orchestrator.apply_chain(params)


@register("export.stl")
def export_stl_cmd(params):
    """
    Export the CURRENT Blender scene's mesh(es) to binary STL(s) in the
    project dir. Requires a prior successful edit.apply_chain (mesh in
    scene) + Blender connected. Never raises across JSON-RPC: structured
    {ok:false,...} on any failure so the Export screen can render it.

    params: {slug, mode("none"|"zebra"|"quarter"), dst_dir?}
    ok: {"ok": true, "mode", "dir", "count", "files":[{path,color,size}]}
    """
    import os
    import time
    from pathlib import Path
    from slugify import slugify
    from ops import export_stl

    slug = slugify(params.get("slug") or "model")
    mode = params.get("mode") or "none"
    dst_dir = params.get("dst_dir") or str(
        Path(os.environ.get("LOCALAPPDATA", Path.home()))
        / "Conjure3D" / "projects" / slug
    )
    ts = time.strftime("%Y%m%d-%H%M%S")
    try:
        result = export_stl.run(dst_dir, slug, ts, mode)
        return {"ok": True, **result}
    except Exception as exc:  # noqa: BLE001 — surface, never raise across RPC
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@register("slicer.launch")
def slicer_launch(params):
    return _slicer.launch(params)


@register("project.save")
def project_save(params):
    return _project.save(params)


@register("project.load")
def project_load(params):
    return _project.load(params)


@register("llm.backend_info")
def llm_backend_info(_params):
    """Cheap, frontend-safe metadata about the active LLM backend. Used by
    the AI Editor's status badge so the user can see whether they're
    talking to the mock (J.2/J.3), local llama.cpp (J.4), or a remote
    API (J.6). Never blocks; never spends a token."""
    return {"backend": _llm.backend_name()}


@register("llm.generate_chain")
def llm_generate_chain(params):
    """Turn a free-form user instruction into a validated edit chain.

    params: {"user_prompt": str, "object_type"?: "vase"|"solid_decorative"|"flat_part",
             "sanity"?: dict — current Sanity snapshot for context}
    returns on success:
        {"ok": True, "edits": [{...}, ...], "backend": str}
    returns on validation failure (LLM emitted something Pydantic can't accept):
        {"ok": False, "error_code": "schema_violation", "message": str}
    returns on any other backend error:
        {"ok": False, "error_code": "backend_error", "message": str}

    We translate exceptions into structured errors here (instead of
    letting them bubble to the dispatcher's generic internal-error path)
    because the AI Editor needs to branch on the failure type: a
    schema_violation gets a "retry with a clearer request" hint; a
    backend_error gets a "the model crashed, fall back to manual" hint.
    """
    user_prompt = params.get("user_prompt", "")
    object_type = params.get("object_type", "solid_decorative")
    sanity = params.get("sanity")
    try:
        chain = _llm.generate_edit_chain(
            user_prompt=user_prompt,
            object_type=object_type,
            sanity=sanity,
        )
    except _PydanticValidationError as exc:
        return {
            "ok": False,
            "error_code": "schema_violation",
            "message": str(exc),
            "backend": _llm.backend_name(),
        }
    except Exception as exc:  # noqa: BLE001 — structured error, never raise across RPC
        return {
            "ok": False,
            "error_code": "backend_error",
            "message": f"{type(exc).__name__}: {exc}",
            "backend": _llm.backend_name(),
        }
    return {
        "ok": True,
        "edits": chain.to_orchestrator_input(),
        "backend": _llm.backend_name(),
    }


def dispatch(req):
    """
    Validate and dispatch one JSON-RPC 2.0 request dict.
    Returns a response dict, or None for notifications (no id).
    """
    req_id = req.get("id")

    if req.get("jsonrpc") != "2.0" or "method" not in req:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32600, "message": "Invalid Request"},
        }

    method = req["method"]
    params = req.get("params") or {}

    if method not in COMMANDS:
        if req_id is None:
            return None
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    try:
        result = COMMANDS[method](params)
    except Exception as exc:
        # Full traceback to stderr. The Tauri host pipes the sidecar's stderr
        # to %LOCALAPPDATA%\Conjure3D\logs\<timestamp>.log (Issue #29), so a
        # crash always leaves a stack trace on disk for the Copy-diagnostic
        # button. The JSON-RPC error stays one-line (data=str(exc)).
        print(
            f"[sidecar] internal error in {method}: {exc}\n"
            f"{traceback.format_exc()}",
            file=sys.stderr,
            flush=True,
        )
        if req_id is None:
            return None
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32603, "message": "Internal error", "data": str(exc)},
        }

    if req_id is None:
        return None

    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def run_loop(stdin=None, stdout=None):
    if stdin is None:
        stdin = sys.stdin
    if stdout is None:
        stdout = sys.stdout

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {exc}"},
            }
            print(json.dumps(response), file=stdout, flush=True)
            continue

        response = dispatch(req)
        if response is not None:
            print(json.dumps(response), file=stdout, flush=True)


if __name__ == "__main__":
    run_loop()
