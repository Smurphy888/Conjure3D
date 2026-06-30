import io
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import slicer
import main


def _settings(bambu_path):
    return {"version": 1, "bambu_path": bambu_path}


def test_error_codes_are_the_frozen_contract():
    # The frontend branches on these exact strings — pin them.
    assert slicer.ERROR_CODES == (
        "BAMBU_PATH_MISSING",
        "BAMBU_PATH_INVALID",
        "NO_STL_FILES",
        "STL_FILES_MISSING",
    )


def test_missing_bambu_path_returns_error_code():
    with patch("slicer.read_settings", return_value=_settings(None)):
        r = slicer.launch({"stl_paths": ["a.stl"]})
    assert r["ok"] is False
    assert r["error_code"] == "BAMBU_PATH_MISSING"
    assert "Settings" in r["message"]


def test_configured_path_not_on_disk_is_invalid(tmp_path):
    ghost = str(tmp_path / "nope" / "bambu-studio.exe")
    with patch("slicer.read_settings", return_value=_settings(ghost)):
        r = slicer.launch({"stl_paths": ["a.stl"]})
    assert r["error_code"] == "BAMBU_PATH_INVALID"


def test_no_stl_files_returns_error_code(tmp_path):
    exe = tmp_path / "bambu-studio.exe"
    exe.write_bytes(b"x")
    with patch("slicer.read_settings", return_value=_settings(str(exe))):
        r = slicer.launch({"stl_paths": []})
    assert r["error_code"] == "NO_STL_FILES"


def test_listed_stl_missing_on_disk(tmp_path):
    exe = tmp_path / "bambu-studio.exe"
    exe.write_bytes(b"x")
    real = tmp_path / "real.stl"
    real.write_bytes(b"x")
    ghost = str(tmp_path / "ghost.stl")
    with patch("slicer.read_settings", return_value=_settings(str(exe))):
        r = slicer.launch({"stl_paths": [str(real), ghost]})
    assert r["error_code"] == "STL_FILES_MISSING"
    assert r["missing"] == [ghost]


def test_success_spawns_with_argv_list_not_shell(tmp_path):
    exe = tmp_path / "bambu-studio.exe"
    exe.write_bytes(b"x")
    s1 = tmp_path / "v_red.stl"
    s1.write_bytes(b"x")
    s2 = tmp_path / "v_yellow.stl"
    s2.write_bytes(b"x")
    calls = {}

    def fake_popen(args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs
        m = MagicMock()
        m.pid = 4242
        return m

    with patch("slicer.read_settings", return_value=_settings(str(exe))), \
         patch("slicer.subprocess.Popen", side_effect=fake_popen):
        r = slicer.launch({"stl_paths": [str(s1), str(s2)]})

    assert r["ok"] is True and r["launched"] is True
    assert r["pid"] == 4242
    assert r["bambu_path"] == str(exe)
    # argv list, exe first, every STL after — never a shell string.
    assert isinstance(calls["args"], list)
    assert calls["args"] == [str(exe), str(s1), str(s2)]
    assert calls["kwargs"]["close_fds"] is True


@pytest.mark.skipif(
    os.name != "nt",
    reason="subprocess.DETACHED_PROCESS is a Windows-only constant",
)
def test_success_uses_detached_flags_on_windows(tmp_path):
    exe = tmp_path / "bambu-studio.exe"
    exe.write_bytes(b"x")
    s1 = tmp_path / "a.stl"
    s1.write_bytes(b"x")
    captured = {}

    def fake_popen(args, **kwargs):
        captured.update(kwargs)
        m = MagicMock()
        m.pid = 1
        return m

    with patch("slicer.os.name", "nt"), \
         patch("slicer.read_settings", return_value=_settings(str(exe))), \
         patch("slicer.subprocess.Popen", side_effect=fake_popen):
        slicer.launch({"stl_paths": [str(s1)]})

    expected = (
        subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    )
    assert captured["creationflags"] == expected


def test_stl_paths_must_be_list_of_str(tmp_path):
    with pytest.raises(TypeError):
        slicer.launch({"stl_paths": "a.stl"})  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        slicer.launch({"stl_paths": [1, 2]})  # type: ignore[list-item]


def test_dispatch_slicer_launch_returns_error_code_over_rpc():
    with patch("slicer.read_settings", return_value=_settings(None)):
        req = json.dumps({
            "jsonrpc": "2.0", "id": 7, "method": "slicer.launch",
            "params": {"stl_paths": ["a.stl"]},
        })
        out = io.StringIO()
        main.run_loop(io.StringIO(req + "\n"), out)
        resp = json.loads(out.getvalue())
    assert resp["result"]["error_code"] == "BAMBU_PATH_MISSING"
