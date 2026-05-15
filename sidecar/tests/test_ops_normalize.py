import json
import socket
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from ops import normalize, import_glb, voxel_remesh, keep_largest
from blender_client import DEFAULT_TIMEOUT


# ── unit tests (mocked, no Blender) ──────────────────────────────────────────

def test_scale_to_longest_rejects_non_positive_target():
    with pytest.raises(ValueError, match="must be positive"):
        normalize.scale_to_longest(0)
    with pytest.raises(ValueError, match="must be positive"):
        normalize.scale_to_longest(-5)


def test_scale_to_longest_rejects_non_numeric_target():
    with pytest.raises(TypeError):
        normalize.scale_to_longest("80")  # type: ignore[arg-type]


def test_scale_to_longest_converts_mm_to_meters_and_bakes_scale():
    captured = {}
    def fake(code, timeout=None, **kwargs):
        captured['code'] = code
        captured['timeout'] = timeout
        return '{"longest_mm": 80.0, "dimensions_mm": [80.0, 20.0, 20.0], "factor": 0.5}'
    with patch("ops.normalize.execute_blender_code", side_effect=fake):
        out = normalize.scale_to_longest(80.0)
    # 80 mm → 0.08 m on the wire
    assert "0.08" in captured['code']
    assert "transform_apply(location=False, rotation=False, scale=True)" in captured['code']
    assert captured['timeout'] == DEFAULT_TIMEOUT
    assert out["longest_mm"] == 80.0


def test_recenter_xy_emits_bbox_translate_and_bakes_location():
    captured = {}
    def fake(code, timeout=None, **kwargs):
        captured['code'] = code
        return '{"center_x_mm": 0.0, "center_y_mm": 0.0, "min_z_mm": 0.0}'
    with patch("ops.normalize.execute_blender_code", side_effect=fake):
        out = normalize.recenter_xy()
    assert "obj.bound_box" in captured['code']
    assert "matrix_world" in captured['code']
    assert "transform_apply(location=True, rotation=False, scale=False)" in captured['code']
    assert out == {"center_x_mm": 0.0, "center_y_mm": 0.0, "min_z_mm": 0.0}


def test_flat_bottom_rejects_non_positive_cut():
    with pytest.raises(ValueError, match="must be positive"):
        normalize.flat_bottom(0)
    with pytest.raises(ValueError, match="must be positive"):
        normalize.flat_bottom(-0.5)


def test_flat_bottom_rejects_non_numeric_cut():
    with pytest.raises(TypeError):
        normalize.flat_bottom("0.8")  # type: ignore[arg-type]


def test_flat_bottom_default_cut_converts_to_meters_and_fills():
    captured = {}
    def fake(code, timeout=None, **kwargs):
        captured['code'] = code
        return '{"min_z_mm": 0.0, "max_z_mm": 79.2, "cut_mm": 0.8}'
    with patch("ops.normalize.execute_blender_code", side_effect=fake):
        out = normalize.flat_bottom()
    # default 0.8 mm → 0.0008 m on the wire
    assert "0.0008" in captured['code']
    assert "bpy.ops.mesh.bisect(" in captured['code']
    assert "use_fill=True" in captured['code']
    assert "plane_no=(0.0, 0.0, 1.0)" in captured['code']
    assert out["cut_mm"] == 0.8


def test_last_json_raises_when_stdout_has_no_json_line():
    with patch("ops.normalize.execute_blender_code", return_value="noise only\n"):
        with pytest.raises(RuntimeError, match="No JSON stats line"):
            normalize.recenter_xy()


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
GUITAR_GLB = str(FIXTURE_DIR / "sample_guitar.glb")


@pytest.mark.skipif(not _port_open(), reason=_LIVE_REASON)
def test_live_scale_to_longest_hits_target_within_tolerance():
    """Acceptance: output longest dim matches target ± 0.1 mm."""
    import_glb.run(VASE_GLB)
    stats = normalize.scale_to_longest(80.0)
    assert abs(stats["longest_mm"] - 80.0) <= 0.1, (
        f"longest dim {stats['longest_mm']} mm not within 0.1 mm of 80 mm"
    )


@pytest.mark.skipif(not _port_open(), reason=_LIVE_REASON)
def test_live_recenter_xy_centers_bbox_and_grounds_base():
    """Acceptance: bbox centered at X=0,Y=0 and bottom Z=0 ± 0.001 mm."""
    import_glb.run(VASE_GLB)
    normalize.scale_to_longest(80.0)
    stats = normalize.recenter_xy()
    assert abs(stats["center_x_mm"]) <= 0.001, f"X not centered: {stats}"
    assert abs(stats["center_y_mm"]) <= 0.001, f"Y not centered: {stats}"
    assert abs(stats["min_z_mm"]) <= 0.001, f"base not on z=0: {stats}"


@pytest.mark.skipif(not _port_open(), reason=_LIVE_REASON)
def test_live_flat_bottom_full_pipeline_leaves_base_on_z0():
    """
    Full Phase-6 prefix on the vase: scale → voxel → keep_largest → recenter
    → flat_bottom. Acceptance: bottom Z is 0 ± 0.001 mm after flat_bottom.
    """
    import_glb.run(VASE_GLB)
    normalize.scale_to_longest(80.0)
    voxel_remesh.run(voxel_size_mm=0.8)
    keep_largest.run()
    normalize.recenter_xy()
    stats = normalize.flat_bottom()
    assert abs(stats["min_z_mm"]) <= 0.001, (
        f"flat_bottom base not on z=0: {stats}"
    )
    assert stats["max_z_mm"] > 0, f"mesh collapsed: {stats}"
