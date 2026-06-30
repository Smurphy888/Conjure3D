"""
Issue #29 — a crashing command must leave a Python stack trace on stderr
(which the Tauri host pipes to the session log file). This is the only
automated proof of "force a sidecar crash; log file contains stack trace"
at the sidecar boundary; the on-disk log + Copy-diagnostic E2E is deferred
to manual-blender-tests.md.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import main
from main import dispatch


def test_raising_command_writes_traceback_to_stderr(capsys):
    def boom(_params):
        raise RuntimeError("kaboom from a handler")

    main.COMMANDS["test.boom"] = boom
    try:
        resp = dispatch({"jsonrpc": "2.0", "id": 99, "method": "test.boom"})
    finally:
        del main.COMMANDS["test.boom"]

    # JSON-RPC contract unchanged: one-line internal error with data.
    assert resp["id"] == 99
    assert resp["error"]["code"] == -32603
    assert resp["error"]["message"] == "Internal error"
    assert "kaboom from a handler" in resp["error"]["data"]

    # The crash left a full Python traceback on stderr.
    err = capsys.readouterr().err
    assert "[sidecar] internal error in test.boom" in err
    assert "Traceback (most recent call last):" in err
    assert "RuntimeError: kaboom from a handler" in err
    assert "in boom" in err  # the raising frame is named


def test_notification_crash_still_logs_traceback(capsys):
    """A notification (no id) returns None but must still log the trace."""
    def boom(_params):
        raise ValueError("silent-ish")

    main.COMMANDS["test.boom2"] = boom
    try:
        resp = dispatch({"jsonrpc": "2.0", "method": "test.boom2"})
    finally:
        del main.COMMANDS["test.boom2"]

    assert resp is None
    err = capsys.readouterr().err
    assert "Traceback (most recent call last):" in err
    assert "ValueError: silent-ish" in err
