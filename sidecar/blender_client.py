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
import threading
import time
from contextlib import contextmanager

from mcp_token import get_or_create_token

HOST = "127.0.0.1"
PORT = 9876


def _payload(code: str) -> bytes:
    """Command envelope incl. the shared auth token (LAUNCH_AUDIT §1.2).
    The hardened addon rejects commands without a matching token; older
    addon versions ignore the extra field, so this is backward-compatible."""
    return json.dumps({
        "type": "execute_code",
        "params": {"code": code},
        "token": get_or_create_token(),
    }).encode("utf-8")

DEFAULT_TIMEOUT = 30.0
HEAVY_TIMEOUT = 120.0
# Bumped from 3 to 5 with capped exponential backoff (max ~10s) so a brief
# addon-state hiccup (the third-party BlenderMCP server thread sometimes
# silently goes dark mid-session) doesn't fail a whole edit chain on the
# very first refused connect. Total worst-case wait per call: ~20s.
DEFAULT_RETRIES = 5
MAX_BACKOFF_SEC = 10.0
RECV_CHUNK = 8192

# Thread-local storage for a "current" persistent session. When set (via the
# session_scope() context manager) every execute_blender_code() call on this
# thread reuses the session's socket instead of opening a fresh connection.
# This is the workaround for the BlenderMCP addon's known stability flaw:
# repeated connect/accept cycles correlate with the addon's daemon server
# thread silently dying after the first main-thread heavy op. One connection
# held for the whole chain avoids that churn entirely; the addon's handler
# already supports multi-command per connection (verified in addon source).
_tls = threading.local()


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

    If a `session_scope()` is active on this thread, the call piggybacks on
    that session's persistent socket. Otherwise opens a fresh one-shot socket.

    Raises BlenderConnectionError if:
    - all connect attempts fail (port closed / Blender not running),
    - the connection is lost after the request is sent,
    - the addon returns status=error or a malformed response.
    """
    if not isinstance(code, str):
        raise TypeError(f"code must be str, got {type(code).__name__}")
    if retries < 1:
        retries = 1

    # Piggyback on an active session if one is bound to this thread.
    # Session calls are for edit chains that may include heavy ops (GLB import,
    # voxel-remesh, decimate); always give them at least HEAVY_TIMEOUT so a
    # slow operation doesn't abort the whole chain at the 30 s socket deadline.
    sess = getattr(_tls, "session", None)
    if sess is not None:
        return sess.execute_code(code, timeout=max(timeout, HEAVY_TIMEOUT))

    payload = _payload(code)

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


class BlenderSession:
    """Persistent connection across an edit chain (orchestrator.apply_chain).

    Usage (typical: via the session_scope() context manager — but the class
    can be used directly if you want explicit lifetime control):

        with BlenderSession() as s:
            s.execute_code(code1, timeout=30)
            s.execute_code(code2, timeout=120)

    One TCP connect at __enter__, each execute_code sends + receives on the
    same socket, close at __exit__. The addon's `_handle_client` already
    supports multi-command per connection (reads until JSON parses, schedules
    a timer per command, loops back to recv).
    """

    def __init__(
        self,
        host: str = HOST,
        port: int = PORT,
        connect_timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
    ):
        self.host = host
        self.port = port
        self._connect_timeout = connect_timeout
        self._retries = max(1, retries)
        self._sock: socket.socket | None = None

    def __enter__(self) -> "BlenderSession":
        self._sock = _connect_with_retry(
            self.host, self.port, self._connect_timeout, self._retries
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        s = self._sock
        self._sock = None
        if s is not None:
            try:
                s.close()
            except OSError:
                pass

    def execute_code(self, code: str, timeout: float = DEFAULT_TIMEOUT) -> str:
        if self._sock is None:
            raise BlenderConnectionError(
                "BlenderSession is not open (use it as a context manager)."
            )
        if not isinstance(code, str):
            raise TypeError(f"code must be str, got {type(code).__name__}")

        payload = _payload(code)

        try:
            self._sock.settimeout(timeout)
            self._sock.sendall(payload)
            resp = _recv_json(self._sock, timeout)
        except socket.timeout as exc:
            raise BlenderConnectionError(
                f"Timed out waiting for Blender response after {timeout}s "
                "(session call). The op may have run anyway; check Blender."
            ) from exc
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError) as exc:
            raise BlenderConnectionError(
                f"Persistent connection lost mid-session: {exc}. "
                "The BlenderMCP server thread may have died — open Blender's "
                "BlenderMCP panel and Disconnect/Connect to MCP server."
            ) from exc
        except OSError as exc:
            raise BlenderConnectionError(
                f"Network error during session request: {exc}"
            ) from exc

        return _unwrap_response(resp)


@contextmanager
def session_scope(
    host: str = HOST,
    port: int = PORT,
    connect_timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
):
    """Bind a persistent BlenderSession to the current thread. Every
    execute_blender_code() call on this thread inside the `with` block reuses
    the session's socket. Ops modules don't need to know about the session —
    they keep calling execute_blender_code(); the thread-local lookup wires
    them to the session transparently.

    Use this around an edit chain (orchestrator.apply_chain). If a session is
    already active on this thread (nested call — shouldn't happen, but safe),
    we yield the existing one instead of opening a second connection.
    """
    existing = getattr(_tls, "session", None)
    if existing is not None:
        yield existing
        return
    with BlenderSession(host, port, connect_timeout, retries) as s:
        _tls.session = s
        try:
            yield s
        finally:
            _tls.session = None


def _connect_with_retry(host: str, port: int, timeout: float, retries: int) -> socket.socket:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            return socket.create_connection((host, port), timeout=timeout)
        except (ConnectionRefusedError, socket.timeout, OSError) as exc:
            last_err = exc
            if attempt < retries - 1:
                # 0.5, 1.0, 2.0, 4.0, 8.0 (capped at MAX_BACKOFF_SEC). Gives the
                # addon's server thread real time to recover (re-enable / watchdog
                # restart) rather than failing the chain on a sub-second blip.
                time.sleep(min(2 ** attempt * 0.5, MAX_BACKOFF_SEC))
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
