import socket
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from ops import vase_top, import_glb, voxel_remesh, keep_largest, normalize
from blender_client import DEFAULT_TIMEOUT


# ── unit tests (mocked, no Blender) ──────────────────────────────────────────

def test_open_top_skips_non_vase_without_touching_blender():
    with patch("ops.vase_top.execute_blender_code") as ec:
        out = vase_top.open_top("solid_decorative")
    ec.assert_not_called()
    assert out == {"skipped": True, "object_type": "solid_decorative"}


def test_bridge_top_loops_skips_non_vase_without_touching_blender():
    with patch("ops.vase_top.execute_blender_code") as ec:
        out = vase_top.bridge_top_loops("solid_decorative")
    ec.assert_not_called()
    assert out == {"skipped": True, "object_type": "solid_decorative"}


def test_open_top_rejects_non_positive_margin():
    with pytest.raises(ValueError, match="must be positive"):
        vase_top.open_top("vase", top_margin_mm=0)
    with pytest.raises(ValueError, match="must be positive"):
        vase_top.open_top("vase", top_margin_mm=-1)


def test_open_top_rejects_non_numeric_margin():
    with pytest.raises(TypeError):
        vase_top.open_top("vase", top_margin_mm="2")  # type: ignore[arg-type]


def test_open_top_vase_code_bisects_and_clears_cap():
    captured = {}
    def fake(code, timeout=None, **kwargs):
        captured['code'] = code
        captured['timeout'] = timeout
        return '{"skipped": false, "boundary_edges": 64, "max_z_mm": 78.0}'
    with patch("ops.vase_top.execute_blender_code", side_effect=fake):
        out = vase_top.open_top("vase", top_margin_mm=2.0)
    # 2 mm → 0.002 m on the wire
    assert "0.002" in captured['code']
    assert "bpy.ops.mesh.bisect(" in captured['code']
    assert "clear_outer=True" in captured['code']
    assert "use_fill=False" in captured['code']
    assert captured['timeout'] == DEFAULT_TIMEOUT
    assert out["skipped"] is False


def test_bridge_top_loops_vase_code_bridges_non_manifold():
    captured = {}
    def fake(code, timeout=None, **kwargs):
        captured['code'] = code
        return '{"skipped": false, "boundary_edges": 0, "watertight": true}'
    with patch("ops.vase_top.execute_blender_code", side_effect=fake):
        out = vase_top.bridge_top_loops("vase")
    assert "select_non_manifold()" in captured['code']
    assert "bridge_edge_loops()" in captured['code']
    assert out["watertight"] is True


def test_vase_top_raises_when_stdout_has_no_json_line():
    with patch("ops.vase_top.execute_blender_code", return_value="nothing\n"):
        with pytest.raises(RuntimeError, match="No JSON stats line"):
            vase_top.open_top("vase")


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
def test_live_open_top_then_bridge_yields_watertight_vase():
    """Acceptance: object_type=='vase' -> top opened then bridged, watertight."""
    import_glb.run(VASE_GLB)
    normalize.scale_to_longest(80.0)
    voxel_remesh.run(voxel_size_mm=0.8)
    keep_largest.run()

    opened = vase_top.open_top("vase", top_margin_mm=2.0)
    assert opened["skipped"] is False
    assert opened["boundary_edges"] > 0, f"top not opened: {opened}"

    bridged = vase_top.bridge_top_loops("vase")
    assert bridged["skipped"] is False
    assert bridged["watertight"] is True, f"not watertight after bridge: {bridged}"


@pytest.mark.skipif(not _port_open(), reason=_LIVE_REASON)
def test_live_solid_decorative_skips_both_ops_unchanged():
    """Acceptance: object_type=='solid_decorative' -> ops skip cleanly."""
    import_glb.run(VASE_GLB)
    assert vase_top.open_top("solid_decorative")["skipped"] is True
    assert vase_top.bridge_top_loops("solid_decorative")["skipped"] is True
