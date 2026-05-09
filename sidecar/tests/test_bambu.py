import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))
from bambu import detect_bambu, _candidates


def test_not_found_when_no_candidates():
    with patch("bambu._candidates", return_value=[]):
        r = detect_bambu()
    assert r == {"found": False, "path": None}


def test_found_at_first_existing_path(tmp_path):
    exe = tmp_path / "bambu-studio.exe"
    exe.write_bytes(b"x")
    with patch("bambu._candidates", return_value=[exe]):
        r = detect_bambu()
    assert r["found"] is True
    assert r["path"] == str(exe)


def test_skips_nonexistent_path(tmp_path):
    missing = tmp_path / "nonexistent" / "bambu-studio.exe"
    real = tmp_path / "bambu-studio.exe"
    real.write_bytes(b"x")
    with patch("bambu._candidates", return_value=[missing, real]):
        r = detect_bambu()
    assert r["found"] is True
    assert r["path"] == str(real)


def test_returns_not_found_when_all_missing(tmp_path):
    missing = tmp_path / "nonexistent" / "bambu-studio.exe"
    with patch("bambu._candidates", return_value=[missing]):
        r = detect_bambu()
    assert r == {"found": False, "path": None}


def test_candidates_uses_argv_arrays_not_shell(monkeypatch, tmp_path):
    """subprocess.run called with list arg, not a shell string."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        m = MagicMock()
        m.stdout = ""
        return m

    monkeypatch.setattr("bambu.subprocess.run", fake_run)
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    _candidates()
    assert any(isinstance(c, list) for c in calls), "subprocess.run must use list args"


def test_dispatch_wizard_detect_bambu():
    import io
    import json
    import main

    with patch("bambu._candidates", return_value=[]):
        req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "wizard.detect_bambu", "params": {}})
        out = io.StringIO()
        main.run_loop(io.StringIO(req + "\n"), out)
        resp = json.loads(out.getvalue())
    assert resp["result"]["found"] is False
