import socket
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from ops import fix_normals, import_glb
from blender_client import DEFAULT_TIMEOUT, execute_blender_code


# ── unit tests (mocked, no Blender) ──────────────────────────────────────────

def test_fix_normals_code_uses_signed_volume_and_flip():
    captured = {}
    def fake(code, timeout=None, **kwargs):
        captured['code'] = code
        captured['timeout'] = timeout
        return '{"volume_before": -1.0, "volume_after": 1.0, "flipped": true}'
    with patch("ops.fix_normals.execute_blender_code", side_effect=fake):
        out = fix_normals.run()
    assert "calc_volume(signed=True)" in captured['code']
    assert "bpy.ops.mesh.flip_normals()" in captured['code']
    assert "volume_before < 0" in captured['code']
    assert captured['timeout'] == DEFAULT_TIMEOUT
    assert out == {"volume_before": -1.0, "volume_after": 1.0, "flipped": True}


def test_fix_normals_returns_not_flipped_when_already_positive():
    payload = '{"volume_before": 2.5, "volume_after": 2.5, "flipped": false}'
    with patch("ops.fix_normals.execute_blender_code", return_value=payload):
        out = fix_normals.run()
    assert out["flipped"] is False
    assert out["volume_after"] == 2.5


def test_fix_normals_raises_when_stdout_has_no_json_line():
    with patch("ops.fix_normals.execute_blender_code", return_value="garbage\n"):
        with pytest.raises(RuntimeError, match="No JSON stats line"):
            fix_normals.run()


# ── live integration tests (skipped when Blender not running) ────────────────

def _port_open(host="127.0.0.1", port=9876, timeout=0.5):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


_LIVE_REASON = "Blender + BlenderMCP not running on :9876"

FIXTURE_DIR = Path(__file__).parent / "fixtures"
VASE_GLB = str(FIXTURE_DIR / "sample_vase.glb")


@pytest.mark.skipif(not _port_open(), reason=_LIVE_REASON)
def test_live_fix_normals_makes_volume_positive_for_vase():
    """Acceptance: signed volume positive after this op for any input."""
    import_glb.run(VASE_GLB)
    stats = fix_normals.run()
    assert stats["volume_after"] > 0, f"vase volume not positive: {stats}"


@pytest.mark.skipif(not _port_open(), reason=_LIVE_REASON)
def test_live_fix_normals_repairs_inside_out_cube():
    """An explicitly inverted cube must come back with positive volume."""
    setup = """\
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=2.0)
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.flip_normals()
bpy.ops.object.mode_set(mode='OBJECT')
"""
    execute_blender_code(setup, timeout=10.0)
    stats = fix_normals.run()
    assert stats["flipped"] is True, f"expected a flip on inverted cube: {stats}"
    assert stats["volume_before"] < 0, f"setup did not invert cube: {stats}"
    assert stats["volume_after"] > 0, f"cube volume not positive: {stats}"
