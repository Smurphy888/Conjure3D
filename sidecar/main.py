"""
JSON-RPC 2.0 sidecar — stdin/stdout, newline-delimited.
All diagnostic output goes to stderr; stdout is the protocol channel only.
"""
import json
import sys
import webbrowser

import keyring

from slugify import slugify as _slugify
from settings import read_settings, write_settings
from blender import detect_blender
from addon import install_addon
from connection import test_socket as _test_socket
from bambu import detect_bambu as _detect_bambu
import meshy_mock as _meshy
import orchestrator as _orchestrator  # real ops chain (Phase E #22)
import slicer as _slicer  # Bambu Studio hand-off (Phase G #25)
import project as _project  # .conjure3d.json save/load (Phase H #26)

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
    return _meshy.set_fixture(params)


@register("edit.apply_chain")
def edit_apply_chain(params):
    return _orchestrator.apply_chain(params)


@register("slicer.launch")
def slicer_launch(params):
    return _slicer.launch(params)


@register("project.save")
def project_save(params):
    return _project.save(params)


@register("project.load")
def project_load(params):
    return _project.load(params)


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
        print(f"[sidecar] internal error in {method}: {exc}", file=sys.stderr)
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
