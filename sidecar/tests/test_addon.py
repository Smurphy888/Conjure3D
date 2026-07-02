import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
from addon import _major_minor, install_addon


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_zip(tmp_path: Path, filenames: list[str]) -> Path:
    """Create a test zip containing empty files with the given names."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    z = tmp_path / "test_addon.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for name in filenames:
            zf.writestr(name, b"# addon placeholder")
    return z


# ── _major_minor ─────────────────────────────────────────────────────────────

def test_major_minor_full():
    assert _major_minor("4.2.3") == "4.2"


def test_major_minor_short():
    assert _major_minor("4.3") == "4.3"


def test_major_minor_too_short():
    import pytest
    with pytest.raises(ValueError):
        _major_minor("4")


# ── install_addon ─────────────────────────────────────────────────────────────

def test_install_extracts_addon_file(tmp_path):
    zip_path = _make_zip(tmp_path / "zip", ["blender_mcp.py"])
    addons_root = tmp_path / "addons_root"

    r = install_addon("4.2.3", zip_path=zip_path, addons_root=addons_root)

    assert r["ok"] is True
    installed = addons_root / "4.2" / "scripts" / "addons" / "blender_mcp.py"
    assert installed.exists()


def test_install_version_truncated_to_major_minor(tmp_path):
    zip_path = _make_zip(tmp_path / "zip", ["blender_mcp.py"])
    addons_root = tmp_path / "addons_root"

    install_addon("4.3.2", zip_path=zip_path, addons_root=addons_root)

    assert (addons_root / "4.3" / "scripts" / "addons" / "blender_mcp.py").exists()


def test_install_creates_parent_dirs(tmp_path):
    zip_path = _make_zip(tmp_path / "zip", ["blender_mcp.py"])
    addons_root = tmp_path / "deep" / "nonexistent" / "root"

    r = install_addon("4.2", zip_path=zip_path, addons_root=addons_root)

    assert r["ok"] is True


def test_install_is_idempotent(tmp_path):
    zip_path = _make_zip(tmp_path / "zip", ["blender_mcp.py"])
    addons_root = tmp_path / "addons_root"

    r1 = install_addon("4.2", zip_path=zip_path, addons_root=addons_root)
    r2 = install_addon("4.2", zip_path=zip_path, addons_root=addons_root)

    assert r1["ok"] is True
    assert r2["ok"] is True


def test_install_missing_zip_returns_error(tmp_path):
    r = install_addon("4.2", zip_path=tmp_path / "no_such.zip", addons_root=tmp_path)
    assert r["ok"] is False
    assert "not found" in r["error"]


def test_install_invalid_version_returns_error(tmp_path):
    r = install_addon("4", zip_path=tmp_path / "x.zip", addons_root=tmp_path)
    assert r["ok"] is False
    assert "major.minor" in r["error"]


def test_install_returns_path_string(tmp_path):
    zip_path = _make_zip(tmp_path / "zip", ["blender_mcp.py"])
    addons_root = tmp_path / "root"

    r = install_addon("4.2", zip_path=zip_path, addons_root=addons_root)

    assert isinstance(r["path"], str)
    assert "addons" in r["path"]


# ── zip-slip guard (S4) ────────────────────────────────────────────────────────

def test_install_rejects_zip_slip_member(tmp_path):
    """A member that escapes the addons dir via ../ must be refused, and no
    file may be written outside the target dir."""
    zip_path = _make_zip(tmp_path / "zip", ["blender_mcp.py", "../../evil.py"])
    addons_root = tmp_path / "addons_root"

    r = install_addon("4.2.3", zip_path=zip_path, addons_root=addons_root)

    assert r["ok"] is False
    assert "zip-slip" in r["error"].lower()
    # The traversal target (addons_root/4.2/scripts/../../evil.py resolves to
    # addons_root/4.2/evil.py? no — ../../ from .../scripts/addons lands in
    # .../4.2). Assert nothing named evil.py exists anywhere under tmp_path.
    assert not list(tmp_path.rglob("evil.py"))


def test_install_absolute_path_member_is_refused(tmp_path):
    """An absolute-path member (Windows drive or POSIX root) must not extract
    outside the addons dir."""
    # zipfile normalises a leading '/', so use an explicit parent-escape which
    # is the portable zip-slip shape.
    zip_path = _make_zip(tmp_path / "zip", ["ok.py", "../../../pwned.py"])
    addons_root = tmp_path / "addons_root"

    r = install_addon("4.2", zip_path=zip_path, addons_root=addons_root)

    assert r["ok"] is False
    assert not list(tmp_path.rglob("pwned.py"))


# ── Hardened-addon source markers ─────────────────────────────────────────────
# The addon must stay a single self-contained .py inside Blender, so its auth
# and watchdog logic is a mirrored copy of the sidecar side. These marker
# tests stop a refactor from silently dropping either half.

_ADDON_SRC = (Path(__file__).parent.parent / "blender_addon" / "blender_mcp.py").read_text(
    encoding="utf-8"
)


def test_addon_has_auth_token_check():
    assert "_get_or_create_auth_token" in _ADDON_SRC
    assert "hmac.compare_digest" in _ADDON_SRC
    assert "auth_failed" in _ADDON_SRC


def test_addon_binds_loopback_not_localhost_name():
    assert "host='127.0.0.1'" in _ADDON_SRC


def test_addon_has_self_heal_watchdog():
    assert "_watchdog" in _ADDON_SRC
    assert "bpy.app.timers.register(self._watchdog" in _ADDON_SRC


def test_addon_token_path_matches_sidecar():
    """Both sides must read %LOCALAPPDATA%/Conjure3D/mcp_token."""
    import mcp_token
    assert 'osp.join(base, "Conjure3D")' in _ADDON_SRC
    assert '"mcp_token"' in _ADDON_SRC
    assert mcp_token.TOKEN_FILENAME == "mcp_token"


def test_addon_version_bumped_for_hardening():
    assert '"version": (1, 3)' in _ADDON_SRC


def test_dispatch_wizard_install_addon(tmp_path):
    """Integration: dispatch wizard.install_addon via the JSON-RPC dispatcher."""
    import json, io
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    import main

    zip_path = _make_zip(tmp_path / "zip", ["blender_mcp.py"])
    addons_root = tmp_path / "root"

    # Patch install_addon to use tmp dirs instead of APPDATA
    original = main.COMMANDS["wizard.install_addon"]
    try:
        main.COMMANDS["wizard.install_addon"] = lambda p: install_addon(
            p["blender_version"], zip_path=zip_path, addons_root=addons_root
        )
        req = json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "wizard.install_addon",
            "params": {"blender_version": "4.2.3"},
        })
        out = io.StringIO()
        main.run_loop(io.StringIO(req + "\n"), out)
        resp = json.loads(out.getvalue())
        assert resp["result"]["ok"] is True
    finally:
        main.COMMANDS["wizard.install_addon"] = original
