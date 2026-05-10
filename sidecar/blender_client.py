"""
TCP socket client for the BlenderMCP addon (port 9876).

Sends Python source code as `execute_code` commands; Blender executes the code
in its embedded interpreter and returns captured stdout.

Wire protocol (no length prefix, no delimiter — buffer until JSON parses):
    Send: {"type": "execute_code", "params": {"code": "<python source>"}}
    Recv: {"status": "success", "result": {"executed": true, "result": "<stdout>"}}
       or {"status": "error",   "message": "<reason>"}

Retry policy:
- Connect-phase failures (refused / OSError before sendall) retry with
  exponential backoff up to `retries` attempts.
- After sendall, we never retry. The Python code may already be running in
  Blender's main thread; a retry could double-execute side-effecting ops.
"""
import json
import socket
import time

HOST = "127.0.0.1"
PORT = 9876

DEFAULT_TIMEOUT = 30.0
HEAVY_TIMEOUT = 120.0
DEFAULT_RETRIES = 3
RECV_CHUNK = 8192


class BlenderConnectionError(RuntimeError):
    """Raised when the BlenderMCP socket cannot be reached, dies mid-call,
    or returns a malformed / error response."""


def execute_blender_code(
    code: str,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    host: str = HOST,
    port: int = PORT,
) -> str:
    """
    Send `code` to BlenderMCP, return captured stdout from the executed snippet.

    Raises BlenderConnectionError if:
    - all connect attempts fail (port closed / Blender not running),
    - the connection is lost after the request is sent,
    - the addon returns status=error or a malformed response.
    """
    if not isinstance(code, str):
        raise TypeError(f"code must be str, got {type(code).__name__}")
    if retries < 1:
        retries = 1

    payload = json.dumps({"type": "execute_code", "params": {"code": code}}).encode("utf-8")

    sock = _connect_with_retry(host, port, timeout, retries)

    try:
        with sock:
            sock.settimeout(timeout)
            sock.sendall(payload)
            resp = _recv_json(sock, timeout)
    except socket.timeout as exc:
        raise BlenderConnectionError(
            f"Timed out waiting for Blender response after {timeout}s. "
            "The op may have run anyway; check Blender."
        ) from exc
    except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError) as exc:
        raise BlenderConnectionError(f"Connection lost after request sent: {exc}") from exc
    except OSError as exc:
        raise BlenderConnectionError(f"Network error during request: {exc}") from exc

    return _unwrap_response(resp)


def _connect_with_retry(host: str, port: int, timeout: float, retries: int) -> socket.socket:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            return socket.create_connection((host, port), timeout=timeout)
        except (ConnectionRefusedError, socket.timeout, OSError) as exc:
            last_err = exc
            if attempt < retries - 1:
                time.sleep(min(2 ** attempt * 0.1, 1.0))
    raise BlenderConnectionError(
        f"Could not connect to Blender at {host}:{port} after {retries} attempts: {last_err}"
    )


def _recv_json(sock: socket.socket, timeout: float) -> dict:
    sock.settimeout(timeout)
    buf = b""
    while True:
        chunk = sock.recv(RECV_CHUNK)
        if not chunk:
            if not buf:
                raise BlenderConnectionError("Connection closed before response received")
            try:
                return json.loads(buf.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise BlenderConnectionError(
                    f"Connection closed mid-stream with partial data: {exc}"
                )
        buf += chunk
        try:
            return json.loads(buf.decode("utf-8"))
        except json.JSONDecodeError:
            continue


def _unwrap_response(resp: dict) -> str:
    status = resp.get("status")
    if status == "error":
        raise BlenderConnectionError(f"BlenderMCP addon error: {resp.get('message', 'unknown')}")
    if status != "success":
        raise BlenderConnectionError(f"Unexpected response shape (no status=success): {resp}")

    result = resp.get("result")
    if not isinstance(result, dict) or not result.get("executed"):
        raise BlenderConnectionError(f"execute_code did not complete cleanly: {result}")

    stdout = result.get("result", "")
    return stdout if isinstance(stdout, str) else ""
