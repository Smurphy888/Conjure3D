import io
import json
import sys
import os

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
