import json
import socket
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))
from connection import test_socket as check_socket


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_socket(recv_data: bytes):
    """Return a mock socket that yields recv_data then b'' on successive recv() calls."""
    sock = MagicMock()
    responses = [recv_data, b""]
    sock.recv.side_effect = responses
    return sock


def _patch_connect(sock_mock):
    """Context manager that makes socket.create_connection return sock_mock."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=sock_mock)
    ctx.__exit__ = MagicMock(return_value=False)
    return patch("connection.socket.create_connection", return_value=ctx)


# ── happy path ────────────────────────────────────────────────────────────────

def test_connected_on_success_response():
    payload = json.dumps({"status": "success", "result": {"name": "Scene", "object_count": 0}}).encode()
    sock = _make_socket(payload)
    with _patch_connect(sock):
        r = check_socket()
    assert r == {"connected": True}


def test_sends_get_scene_info_command():
    payload = json.dumps({"status": "success", "result": {}}).encode()
    sock = _make_socket(payload)
    with _patch_connect(sock):
        check_socket()
    sent = sock.sendall.call_args[0][0]
    cmd = json.loads(sent.decode())
    assert cmd["type"] == "get_scene_info"


# ── error responses from the addon ────────────────────────────────────────────

def test_addon_error_response():
    payload = json.dumps({"status": "error", "message": "bpy.ops poll failed"}).encode()
    sock = _make_socket(payload)
    with _patch_connect(sock):
        r = check_socket()
    assert r["connected"] is False
    assert "bpy.ops poll failed" in r["error"]


def test_garbage_response_not_addon():
    sock = _make_socket(b"HTTP/1.1 400 Bad Request\r\n")
    with _patch_connect(sock):
        r = check_socket()
    assert r["connected"] is False
    assert "not from BlenderMCP" in r["error"]


def test_valid_json_no_status_field_not_addon():
    payload = json.dumps({"message": "hello"}).encode()
    sock = _make_socket(payload)
    with _patch_connect(sock):
        r = check_socket()
    assert r["connected"] is False
    assert "not from BlenderMCP" in r["error"]


def test_empty_response():
    sock = _make_socket(b"")
    with _patch_connect(sock):
        r = check_socket()
    assert r["connected"] is False
    assert "no data" in r["error"]


# ── network-level failures ────────────────────────────────────────────────────

def test_connection_refused():
    with patch("connection.socket.create_connection", side_effect=ConnectionRefusedError):
        r = check_socket()
    assert r["connected"] is False
    assert "refused" in r["error"].lower()


def test_connection_timeout():
    with patch("connection.socket.create_connection", side_effect=socket.timeout):
        r = check_socket()
    assert r["connected"] is False
    assert "timed out" in r["error"].lower()


def test_os_error():
    with patch("connection.socket.create_connection", side_effect=OSError("network unreachable")):
        r = check_socket()
    assert r["connected"] is False
    assert "network error" in r["error"].lower()


# ── recv timeout mid-read ────────────────────────────────────────────────────

def test_recv_timeout_after_garbage():
    sock = MagicMock()
    sock.recv.side_effect = [b"not json", socket.timeout]
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=sock)
    ctx.__exit__ = MagicMock(return_value=False)
    with patch("connection.socket.create_connection", return_value=ctx):
        r = check_socket()
    assert r["connected"] is False
    assert "not from BlenderMCP" in r["error"]


# ── dispatcher integration ────────────────────────────────────────────────────

def test_dispatch_wizard_test_socket():
    import io
    import main

    payload = json.dumps({"status": "success", "result": {"name": "Scene"}}).encode()
    sock = _make_socket(payload)

    original = main.COMMANDS["wizard.test_socket"]
    try:
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=sock)
        ctx.__exit__ = MagicMock(return_value=False)
        with patch("connection.socket.create_connection", return_value=ctx):
            req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "wizard.test_socket", "params": {}})
            out = io.StringIO()
            main.run_loop(io.StringIO(req + "\n"), out)
            resp = json.loads(out.getvalue())
            assert resp["result"]["connected"] is True
    finally:
        main.COMMANDS["wizard.test_socket"] = original
