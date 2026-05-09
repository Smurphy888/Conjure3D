import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))
import blender
from blender import _version_from_exe, detect_blender


def _mock_run(stdout_text):
    m = MagicMock()
    m.stdout = stdout_text
    m.stderr = ""
    return m


def test_not_found_when_no_candidates():
    with patch("blender._candidates", return_value=[]):
        r = detect_blender()
    assert r == {"found": False, "path": None, "version": None}


def test_version_parsing_full(tmp_path):
    exe = tmp_path / "blender.exe"
    exe.write_bytes(b"x")
    with patch("blender.subprocess.run", return_value=_mock_run("Blender 4.2.3 LTS (hash abc)\n")):
        v = _version_from_exe(exe)
    assert v == "4.2.3"


def test_version_parsing_short(tmp_path):
    exe = tmp_path / "blender.exe"
    exe.write_bytes(b"x")
    with patch("blender.subprocess.run", return_value=_mock_run("Blender 4.3 (hash abc)\n")):
        v = _version_from_exe(exe)
    assert v == "4.3"


def test_version_from_exe_returns_none_on_exception(tmp_path):
    exe = tmp_path / "blender.exe"
    exe.write_bytes(b"x")
    with patch("blender.subprocess.run", side_effect=TimeoutError("timeout")):
        v = _version_from_exe(exe)
    assert v is None


def test_detect_blender_found(tmp_path):
    exe = tmp_path / "blender.exe"
    exe.write_bytes(b"x")
    with patch("blender._candidates", return_value=[exe]):
        with patch("blender.subprocess.run", return_value=_mock_run("Blender 4.3.0 (hash dead)\n")):
            r = detect_blender()
    assert r["found"] is True
    assert r["version"] == "4.3.0"
    assert r["path"].endswith("blender.exe")


def test_skips_exe_that_returns_no_version(tmp_path):
    bad = tmp_path / "blender_bad.exe"
    bad.write_bytes(b"x")
    good = tmp_path / "blender_good.exe"
    good.write_bytes(b"x")

    def fake_version(exe):
        return None if exe == bad else "4.2.0"

    with patch("blender._candidates", return_value=[bad, good]):
        with patch("blender._version_from_exe", side_effect=fake_version):
            r = detect_blender()
    assert r["found"] is True
    assert r["version"] == "4.2.0"


def test_skips_missing_exe(tmp_path):
    missing = tmp_path / "nonexistent.exe"
    with patch("blender._candidates", return_value=[missing]):
        r = detect_blender()
    assert r["found"] is False
