import socket
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from ops import color_split, import_glb, voxel_remesh, keep_largest, normalize
from blender_client import HEAVY_TIMEOUT, execute_blender_code


# ── unit tests (mocked, no Blender) ──────────────────────────────────────────

def test_color_split_none_skips_without_touching_blender():
    with patch("ops.color_split.execute_blender_code") as ec:
        out = color_split.run("none")
    ec.assert_not_called()
    assert out == {"skipped": True, "mode": "none"}


def test_color_split_rejects_unknown_mode():
    with pytest.raises(ValueError, match="mode must be one of"):
        color_split.run("rainbow")


def test_zebra_rejects_bad_count():
    with pytest.raises(ValueError, match="zebra count must be >= 2"):
        color_split.run("zebra", count=1)
    with pytest.raises(TypeError):
        color_split.run("zebra", count=8.0)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        color_split.run("zebra", count=True)


def test_zebra_code_uses_bisect_fill_and_two_groups():
    captured = {}
    def fake(code, timeout=None, **kwargs):
        captured['code'] = code
        captured['timeout'] = timeout
        return '{"skipped": false, "mode": "zebra", "objects": 2, "bands": 8}'
    with patch("ops.color_split.execute_blender_code", side_effect=fake):
        out = color_split.run("zebra", count=8)
    code = captured['code']
    assert "bpy.ops.mesh.bisect(" in code
    assert "use_fill=True" in code
    assert "N = 8" in code
    assert "Conjure_ColorA" in code and "Conjure_ColorB" in code
    assert captured['timeout'] == HEAVY_TIMEOUT
    assert out == {"skipped": False, "mode": "zebra", "objects": 2, "bands": 8}


def test_quarter_code_uses_boolean_intersect_exact():
    """Quarter produces 4 geometric wedges via Boolean INTERSECT EXACT,
    no horizontal banding, no material assignment. Regression for: old
    quarter created 2 bands x 4 wedges = 8 objects with 2 colours."""
    captured = {}
    def fake(code, timeout=None, **kwargs):
        captured['code'] = code
        return '{"skipped": false, "mode": "quarter", "objects": 4, "wedges": 4}'
    with patch("ops.color_split.execute_blender_code", side_effect=fake):
        out = color_split.run("quarter")
    code = captured['code']
    assert "type='BOOLEAN'" in code
    assert "m.operation = 'INTERSECT'" in code
    assert "m.solver = 'EXACT'" in code
    assert code.count("_cutter(") >= 4  # four cutter cubes
    assert "_slab(band," not in code     # _slab defined in preamble but not called
    assert "_assign(wedge," not in code  # no colour assignment on wedges
    assert "Conjure_Q{qi}" in code      # single index names (no bi prefix)
    assert out["objects"] == 4
    assert out["wedges"] == 4


def test_color_split_raises_when_stdout_has_no_json_line():
    with patch("ops.color_split.execute_blender_code", return_value="zzz\n"):
        with pytest.raises(RuntimeError, match="No JSON stats line"):
            color_split.run("zebra", count=4)


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


def _signed_volume_of_all_meshes() -> float:
    code = """\
import bpy, bmesh, json
total = 0.0
for o in bpy.context.scene.objects:
    if o.type == 'MESH':
        bm = bmesh.new(); bm.from_mesh(o.data)
        total += abs(bm.calc_volume(signed=True)); bm.free()
print(json.dumps({"volume": total}))
"""
    out = execute_blender_code(code, timeout=30.0)
    for line in reversed(out.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            import json
            return json.loads(line)["volume"]
    raise RuntimeError("no volume line")


def _prep_vase():
    import_glb.run(VASE_GLB)
    normalize.scale_to_longest(80.0)
    voxel_remesh.run(voxel_size_mm=0.8)
    keep_largest.run()


@pytest.mark.skipif(not _port_open(), reason=_LIVE_REASON)
def test_live_zebra_8_yields_two_meshes_volume_preserved():
    """Acceptance: zebra count=8 -> 2 meshes, total volume within 1%."""
    _prep_vase()
    before = _signed_volume_of_all_meshes()
    stats = color_split.run("zebra", count=8)
    assert stats == {"skipped": False, "mode": "zebra", "objects": 2, "bands": 8}
    after = _signed_volume_of_all_meshes()
    assert abs(after - before) / before <= 0.01, f"volume drift: {before}->{after}"


@pytest.mark.skipif(not _port_open(), reason=_LIVE_REASON)
def test_live_quarter_yields_four_meshes_volume_preserved():
    """Acceptance: quarter -> 4 geometric wedges, volume sum within 1%."""
    _prep_vase()
    before = _signed_volume_of_all_meshes()
    stats = color_split.run("quarter")
    assert stats["objects"] == 4 and stats["wedges"] == 4
    after = _signed_volume_of_all_meshes()
    assert abs(after - before) / before <= 0.01, f"volume drift: {before}->{after}"
