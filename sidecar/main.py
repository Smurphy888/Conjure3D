"""
JSON-RPC 2.0 sidecar — stdin/stdout, newline-delimited.
All diagnostic output goes to stderr; stdout is the protocol channel only.
"""
import json
import sys

from slugify import slugify as _slugify
from settings import read_settings, write_settings

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
