import socket
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from ops import decimate, import_glb, voxel_remesh, keep_largest, normalize
from blender_client import HEAVY_TIMEOUT, execute_blender_code


# ── unit tests (mocked, no Blender) ──────────────────────────────────────────

def test_decimate_rejects_non_positive_target():
    with pytest.raises(ValueError, match="must be positive"):
        decimate.run(0)
    with pytest.raises(ValueError, match="must be positive"):
        decimate.run(-100)


def test_decimate_rejects_non_int_target():
    with pytest.raises(TypeError):
        decimate.run(50000.0)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        decimate.run(True)  # bool is not a valid face count


def test_decimate_code_uses_collapse_modifier_and_ratio():
    captured = {}
    def fake(code, timeout=None, **kwargs):
        captured['code'] = code
        captured['timeout'] = timeout
        return ('{"faces_before": 500000, "faces_after": 50000, '
                '"target_faces": 50000, "ratio": 0.1}')
    with patch("ops.decimate.execute_blender_code", side_effect=fake):
        out = decimate.run(50000)
    assert "type='DECIMATE'" in captured['code']
    assert "decimate_type = 'COLLAPSE'" in captured['code']
    assert "modifier_apply" in captured['code']
    assert "ratio = target / faces_before" in captured['code']
    assert captured['timeout'] == HEAVY_TIMEOUT
    assert out["faces_after"] == 50000


def test_decimate_default_target_is_50000():
    captured = {}
    def fake(code, timeout=None, **kwargs):
        captured['code'] = code
        return ('{"faces_before": 10, "faces_after": 10, '
                '"target_faces": 50000, "ratio": 1.0}')
    with patch("ops.decimate.execute_blender_code", side_effect=fake):
        decimate.run()
    assert "target = 50000" in captured['code']


def test_decimate_raises_when_stdout_has_no_json_line():
    with patch("ops.decimate.execute_blender_code", return_value="nope\n"):
        with pytest.raises(RuntimeError, match="No JSON stats line"):
            decimate.run()


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
def test_live_decimate_voxel_remeshed_vase_hits_target():
    """
    Acceptance: decimate brings a voxel-remeshed mesh to <= target face
    count; for voxel-remeshed inputs the applied ratio is < 0.1.
    """
    import_glb.run(VASE_GLB)
    normalize.scale_to_longest(80.0)
    voxel_remesh.run(voxel_size_mm=0.8)
    keep_largest.run()
    stats = decimate.run(50_000)
    assert stats["faces_after"] <= 50_000, f"target not met: {stats}"
    assert stats["faces_after"] < stats["faces_before"], f"no reduction: {stats}"
    assert stats["ratio"] < 0.1, f"voxel-remeshed ratio not < 0.1: {stats}"


@pytest.mark.skipif(not _port_open(), reason=_LIVE_REASON)
def test_live_decimate_skips_small_mesh():
    """A mesh already under target is left untouched (ratio 1.0)."""
    setup = """\
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=2.0)
"""
    execute_blender_code(setup, timeout=10.0)
    stats = decimate.run(50_000)
    assert stats["ratio"] == 1.0, f"small mesh should be untouched: {stats}"
    assert stats["faces_after"] == stats["faces_before"], f"mesh changed: {stats}"
