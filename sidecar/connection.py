"""
wizard.test_socket: TCP ping to the BlenderMCP server at 127.0.0.1:9876.
Sends a get_scene_info command and validates the response to distinguish
"BlenderMCP addon running" from "something else on that port".
"""
import json
import socket

HOST = "127.0.0.1"
PORT = 9876
TIMEOUT = 2.0

_PING = json.dumps({"type": "get_scene_info", "params": {}}).encode()


def test_socket(host: str = HOST, port: int = PORT, timeout: float = TIMEOUT) -> dict:
    """
    Returns {"connected": True} when BlenderMCP responds correctly,
    {"connected": False, "error": str} otherwise with a descriptive message.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.sendall(_PING)
            sock.settimeout(timeout)
            buf = b""
            while True:
                try:
                    chunk = sock.recv(4096)
                except socket.timeout:
                    break
                if not chunk:
                    break
                buf += chunk
                try:
                    resp = json.loads(buf.decode())
                    if resp.get("status") == "success":
                        return {"connected": True}
                    if "status" not in resp:
                        return {
                            "connected": False,
                            "error": "Port 9876 is open but response was not from BlenderMCP addon",
                        }
                    return {
                        "connected": False,
                        "error": f"BlenderMCP addon error: {resp.get('message', 'unexpected response')}",
                    }
                except json.JSONDecodeError:
                    pass  # incomplete; keep reading
            if buf:
                return {
                    "connected": False,
                    "error": "Port 9876 is open but response was not from BlenderMCP addon",
                }
            return {
                "connected": False,
                "error": "Connection succeeded but no data received",
            }
    except ConnectionRefusedError:
        return {
            "connected": False,
            "error": (
                "Connection refused — open Blender and click "
                "'Connect to Claude' in the BlenderMCP panel"
            ),
        }
    except socket.timeout:
        return {
            "connected": False,
            "error": "Connection timed out — Blender may still be loading",
        }
    except OSError as exc:
        return {"connected": False, "error": f"Network error: {exc}"}
