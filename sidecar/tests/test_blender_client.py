import json
import socket
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from blender_client import (
    BlenderConnectionError,
    execute_blender_code,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _success_payload(stdout: str = "ok\n") -> bytes:
    return json.dumps({
        "status": "success",
        "result": {"executed": True, "result": stdout},
    }).encode("utf-8")


def _make_socket(recv_chunks):
    """Mock socket whose recv() yields each chunk in order, then b'' (closed)."""
    sock = MagicMock()
    sock.recv.side_effect = list(recv_chunks) + [b""]
    return sock


def _patch_connect(sock_mock):
    return patch("blender_client.socket.create_connection", return_value=sock_mock)


# ── happy path ────────────────────────────────────────────────────────────────

def test_returns_captured_stdout():
    sock = _make_socket([_success_payload("hello from blender\n")])
    with _patch_connect(sock):
        out = execute_blender_code("print('hello from blender')")
    assert out == "hello from blender\n"


def test_sends_execute_code_command_with_code_param():
    sock = _make_socket([_success_payload()])
    with _patch_connect(sock):
        execute_blender_code("import bpy\nprint(len(bpy.data.objects))")
    sent = sock.sendall.call_args[0][0]
    cmd = json.loads(sent.decode("utf-8"))
    assert cmd["type"] == "execute_code"
    assert cmd["params"]["code"] == "import bpy\nprint(len(bpy.data.objects))"


def test_chunked_response_is_buffered_until_complete():
    payload = _success_payload("chunked\n")
    half = len(payload) // 2
    sock = _make_socket([payload[:half], payload[half:]])
    with _patch_connect(sock):
        out = execute_blender_code("print('chunked')")
    assert out == "chunked\n"


def test_empty_string_stdout_returned_cleanly():
    sock = _make_socket([_success_payload("")])
    with _patch_connect(sock):
        out = execute_blender_code("x = 1")
    assert out == ""


# ── addon-level errors ────────────────────────────────────────────────────────

def test_addon_status_error_raises():
    err = json.dumps({"status": "error", "message": "bpy.ops.poll() failed"}).encode("utf-8")
    sock = _make_socket([err])
    with _patch_connect(sock):
        with pytest.raises(BlenderConnectionError, match="bpy.ops.poll"):
            execute_blender_code("bpy.ops.do.something()")


def test_unexpected_status_raises():
    payload = json.dumps({"status": "weird"}).encode("utf-8")
    sock = _make_socket([payload])
    with _patch_connect(sock):
        with pytest.raises(BlenderConnectionError, match="Unexpected response shape"):
            execute_blender_code("x = 1")


def test_executed_false_raises():
    payload = json.dumps({
        "status": "success",
        "result": {"executed": False, "result": ""},
    }).encode("utf-8")
    sock = _make_socket([payload])
    with _patch_connect(sock):
        with pytest.raises(BlenderConnectionError, match="did not complete cleanly"):
            execute_blender_code("x = 1")


def test_result_not_dict_raises():
    payload = json.dumps({"status": "success", "result": "raw-string"}).encode("utf-8")
    sock = _make_socket([payload])
    with _patch_connect(sock):
        with pytest.raises(BlenderConnectionError, match="did not complete cleanly"):
            execute_blender_code("x = 1")


# ── connect-phase retry ───────────────────────────────────────────────────────

def test_connect_refused_after_retries_raises_connection_error():
    with patch("blender_client.socket.create_connection", side_effect=ConnectionRefusedError):
        with patch("blender_client.time.sleep"):
            with pytest.raises(BlenderConnectionError, match="Could not connect.*after 3 attempts"):
                execute_blender_code("x = 1", retries=3)


def test_connect_retries_then_succeeds():
    sock = _make_socket([_success_payload("ok\n")])
    side_effects = [ConnectionRefusedError(), ConnectionRefusedError(), sock]
    with patch("blender_client.socket.create_connection", side_effect=side_effects):
        with patch("blender_client.time.sleep") as fake_sleep:
            out = execute_blender_code("print('ok')", retries=3)
    assert out == "ok\n"
    # Two backoff sleeps should have been issued (between attempts 1→2 and 2→3).
    assert fake_sleep.call_count == 2


def test_connect_oserror_is_retried():
    with patch("blender_client.socket.create_connection", side_effect=OSError("network unreachable")):
        with patch("blender_client.time.sleep"):
            with pytest.raises(BlenderConnectionError, match="Could not connect"):
                execute_blender_code("x = 1", retries=2)


# ── post-send: must NOT retry, must raise ────────────────────────────────────

def test_connection_reset_after_send_raises_no_retry():
    sock = MagicMock()
    sock.recv.side_effect = ConnectionResetError("reset by peer")
    with patch("blender_client.socket.create_connection", return_value=sock) as creator:
        with pytest.raises(BlenderConnectionError, match="Connection lost"):
            execute_blender_code("print('side-effect')", retries=3)
    # Critical: only ONE connect attempt — once code is on the wire, no retry.
    assert creator.call_count == 1


def test_timeout_after_send_raises_no_retry():
    sock = MagicMock()
    sock.recv.side_effect = socket.timeout
    with patch("blender_client.socket.create_connection", return_value=sock) as creator:
        with pytest.raises(BlenderConnectionError, match="Timed out"):
            execute_blender_code("import time; time.sleep(999)", retries=3)
    assert creator.call_count == 1


def test_empty_recv_immediately_raises():
    sock = MagicMock()
    sock.recv.return_value = b""
    with patch("blender_client.socket.create_connection", return_value=sock):
        with pytest.raises(BlenderConnectionError, match="closed before response"):
            execute_blender_code("x = 1")


def test_partial_data_then_close_raises():
    sock = MagicMock()
    sock.recv.side_effect = [b'{"status":"succ', b""]  # closed mid-JSON
    with patch("blender_client.socket.create_connection", return_value=sock):
        with pytest.raises(BlenderConnectionError, match="closed mid-stream"):
            execute_blender_code("x = 1")


# ── input validation ──────────────────────────────────────────────────────────

def test_non_string_code_raises_type_error():
    with pytest.raises(TypeError):
        execute_blender_code(b"print('bytes')")  # type: ignore[arg-type]


# ── module surface ────────────────────────────────────────────────────────────

def test_blender_client_not_wired_into_main_yet():
    """Issue #15 ships the client module only. Dispatcher wiring is Issue #22."""
    import main
    method_names = list(main.COMMANDS.keys())
    assert not any(m.startswith("blender.") for m in method_names), (
        f"blender.* commands must not be exposed before Issue #22; found: {method_names}"
    )


# ── live integration (skipped when Blender isn't running) ────────────────────

def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.mark.skipif(
    not _port_open("127.0.0.1", 9876),
    reason="Blender + BlenderMCP not running on :9876 (live integration test)",
)
def test_live_round_trip_print_returns_stdout():
    out = execute_blender_code("print('hello from blender')")
    assert "hello from blender" in out
