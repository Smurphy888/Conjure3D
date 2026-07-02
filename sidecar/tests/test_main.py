import io
import json
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from main import dispatch, run_loop


def test_ping_returns_pong():
    req = {"jsonrpc": "2.0", "id": 1, "method": "system.ping"}
    resp = dispatch(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    assert resp["result"]["ok"] is True
    assert resp["result"]["msg"] == "pong"


def test_unknown_method_error():
    req = {"jsonrpc": "2.0", "id": 2, "method": "does.not.exist"}
    resp = dispatch(req)
    assert resp["id"] == 2
    assert "error" in resp
    assert resp["error"]["code"] == -32601


def test_invalid_request_error():
    req = {"jsonrpc": "2.0", "id": 3}
    resp = dispatch(req)
    assert resp["error"]["code"] == -32600


def test_notification_no_response():
    # No id = notification; dispatch returns None
    req = {"jsonrpc": "2.0", "method": "system.ping"}
    assert dispatch(req) is None


def test_run_loop_ping():
    stdin = io.StringIO('{"jsonrpc":"2.0","id":1,"method":"system.ping"}\n')
    stdout = io.StringIO()
    run_loop(stdin=stdin, stdout=stdout)
    stdout.seek(0)
    resp = json.loads(stdout.readline())
    assert resp["result"]["ok"] is True
    assert resp["result"]["msg"] == "pong"


def test_run_loop_unknown_method():
    stdin = io.StringIO('{"jsonrpc":"2.0","id":2,"method":"does.not.exist"}\n')
    stdout = io.StringIO()
    run_loop(stdin=stdin, stdout=stdout)
    stdout.seek(0)
    resp = json.loads(stdout.readline())
    assert resp["error"]["code"] == -32601


def test_run_loop_parse_error():
    stdin = io.StringIO("not valid json\n")
    stdout = io.StringIO()
    run_loop(stdin=stdin, stdout=stdout)
    stdout.seek(0)
    resp = json.loads(stdout.readline())
    assert resp["error"]["code"] == -32700


# ── meshy key commands ─────────────────────────────────────────────────────────

def test_set_meshy_key_returns_ok():
    with patch("main.keyring.set_password") as mock_set:
        req = {"jsonrpc": "2.0", "id": 10, "method": "system.set_meshy_key", "params": {"key": "test_key_value"}}
        resp = dispatch(req)
    assert resp["result"]["ok"] is True
    mock_set.assert_called_once_with("conjure3d", "meshy_api_key", "test_key_value")


def test_set_meshy_key_does_not_echo_key():
    """Key must never appear in the response."""
    with patch("main.keyring.set_password"):
        req = {"jsonrpc": "2.0", "id": 11, "method": "system.set_meshy_key", "params": {"key": "secret_abc123"}}
        resp = dispatch(req)
    resp_str = json.dumps(resp)
    assert "secret_abc123" not in resp_str


def test_has_meshy_key_true_when_set():
    with patch("main.keyring.get_password", return_value="somekey"):
        req = {"jsonrpc": "2.0", "id": 12, "method": "system.has_meshy_key", "params": {}}
        resp = dispatch(req)
    assert resp["result"]["set"] is True


def test_has_meshy_key_false_when_not_set():
    with patch("main.keyring.get_password", return_value=None):
        req = {"jsonrpc": "2.0", "id": 13, "method": "system.has_meshy_key", "params": {}}
        resp = dispatch(req)
    assert resp["result"]["set"] is False


def test_has_meshy_key_false_when_empty_string():
    with patch("main.keyring.get_password", return_value=""):
        req = {"jsonrpc": "2.0", "id": 14, "method": "system.has_meshy_key", "params": {}}
        resp = dispatch(req)
    assert resp["result"]["set"] is False


def test_set_meshy_key_run_loop_integration():
    with patch("main.keyring.set_password"):
        stdin = io.StringIO(
            json.dumps({"jsonrpc": "2.0", "id": 15, "method": "system.set_meshy_key", "params": {"key": "k"}}) + "\n"
        )
        stdout = io.StringIO()
        run_loop(stdin=stdin, stdout=stdout)
        stdout.seek(0)
        resp = json.loads(stdout.readline())
    assert resp["result"]["ok"] is True


# ── system.open_url scheme guard (S1) ──────────────────────────────────────────

def test_open_url_allows_https():
    with patch("main.webbrowser.open") as mock_open:
        req = {"jsonrpc": "2.0", "id": 20, "method": "system.open_url",
               "params": {"url": "https://conjure3d.app/docs"}}
        resp = dispatch(req)
    assert resp["result"]["ok"] is True
    mock_open.assert_called_once_with("https://conjure3d.app/docs")


def test_open_url_allows_http():
    with patch("main.webbrowser.open") as mock_open:
        req = {"jsonrpc": "2.0", "id": 21, "method": "system.open_url",
               "params": {"url": "http://localhost:1420/x"}}
        resp = dispatch(req)
    assert resp["result"]["ok"] is True
    mock_open.assert_called_once()


def test_open_url_rejects_file_scheme_and_does_not_open():
    with patch("main.webbrowser.open") as mock_open:
        req = {"jsonrpc": "2.0", "id": 22, "method": "system.open_url",
               "params": {"url": "file:///C:/Windows/System32/calc.exe"}}
        resp = dispatch(req)
    # ValueError bubbles to the dispatcher's internal-error path; crucially the
    # OS is never asked to open the non-web URL.
    assert "error" in resp
    mock_open.assert_not_called()


def test_open_url_rejects_custom_handler_scheme():
    for bad in ("javascript:alert(1)", "ms-msdt:/id", "vscode://x", "smb://host/share"):
        with patch("main.webbrowser.open") as mock_open:
            req = {"jsonrpc": "2.0", "id": 23, "method": "system.open_url",
                   "params": {"url": bad}}
            resp = dispatch(req)
        assert "error" in resp, f"{bad!r} should be rejected"
        mock_open.assert_not_called()
