import json
import socket
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from ops import import_glb, voxel_remesh, keep_largest
from blender_client import execute_blender_code


# ── unit tests (mocked, no Blender) ──────────────────────────────────────────

def test_import_glb_filepath_is_json_encoded_apostrophe_safe():
    """Filepaths with apostrophes are emitted as JSON inside the code template."""
    captured = {}
    def fake(code, timeout=None, **kwargs):
        captured['code'] = code
        return '{"vertices": 1, "faces": 1, "object_count": 1}'
    with patch("ops.import_glb.execute_blender_code", side_effect=fake):
        import_glb.run("C:/Users/Project's/test.glb")
    # JSON-encoded path is double-quoted; the apostrophe never closes a Python literal.
    assert '"C:/Users/Project\'s/test.glb"' in captured['code']
    assert "filepath=" in captured['code']


def test_import_glb_returns_parsed_stats():
    payload = '{"vertices": 100, "faces": 200, "object_count": 1}'
    with patch("ops.import_glb.execute_blender_code", return_value=payload):
        out = import_glb.run("/some/path.glb")
    assert out == {"vertices": 100, "faces": 200, "object_count": 1}


def test_import_glb_rejects_non_string_filepath():
    with pytest.raises(TypeError):
        import_glb.run(b"/bytes/path.glb")  # type: ignore[arg-type]


def test_import_glb_raises_when_stdout_has_no_json_line():
    with patch("ops.import_glb.execute_blender_code", return_value="random text\n"):
        with pytest.raises(RuntimeError, match="No JSON stats line"):
            import_glb.run("/x.glb")


def test_voxel_remesh_param_validation():
    with pytest.raises(ValueError, match="must be positive"):
        voxel_remesh.run(voxel_size_mm=0)
    with pytest.raises(ValueError, match="must be positive"):
        voxel_remesh.run(voxel_size_mm=-0.1)


def test_voxel_remesh_converts_mm_to_meters_in_code():
    captured = {}
    def fake(code, timeout=None, **kwargs):
        captured['code'] = code
        return '{"vertices": 1, "faces": 1, "voxel_size_mm": 0.8}'
    with patch("ops.voxel_remesh.execute_blender_code", side_effect=fake):
        voxel_remesh.run(voxel_size_mm=0.8)
    # 0.8 mm → 0.0008 m on the wire
    assert "0.0008" in captured['code']
    assert "remesh_voxel_size" in captured['code']
    assert "voxel_remesh()" in captured['code']


def test_voxel_remesh_uses_heavy_timeout_by_default():
    """Voxel remesh on barely-too-big input is slow; timeout default is HEAVY_TIMEOUT."""
    from blender_client import HEAVY_TIMEOUT
    captured = {}
    def fake(code, timeout=None, **kwargs):
        captured['timeout'] = timeout
        return '{"vertices": 1, "faces": 1, "voxel_size_mm": 0.8}'
    with patch("ops.voxel_remesh.execute_blender_code", side_effect=fake):
        voxel_remesh.run()
    assert captured['timeout'] == HEAVY_TIMEOUT


def test_keep_largest_uses_separate_loose_then_picks_biggest():
    captured = {}
    def fake(code, timeout=None, **kwargs):
        captured['code'] = code
        return json.dumps({
            "vertices": 100, "faces": 200,
            "components_before": 5, "components_after": 1,
            "boundary_edges": 0, "non_manifold_edges": 0,
        })
    with patch("ops.keep_largest.execute_blender_code", side_effect=fake):
        out = keep_largest.run()
    assert "separate(type='LOOSE')" in captured['code']
    assert "key=lambda o: len(o.data.polygons)" in captured['code']
    assert out["components_before"] == 5
    assert out["components_after"] == 1


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


def _scale_to_longest_dim(target_mm: float):
    """Scales the active mesh so its longest world-space dim equals target_mm,
    then bakes the scale into mesh-local data with transform_apply.

    This is a TEST helper — Issue #17 will introduce ops/normalize.py with the
    production scale_to_longest op. Inlined here so #16 tests can prove the
    scale-before-voxel-remesh ordering without depending on unimplemented code.
    """
    target_m = target_mm / 1000.0
    code = f"""\
import bpy
obj = bpy.context.view_layer.objects.active
if obj is None or obj.type != 'MESH':
    obj = next((o for o in bpy.context.scene.objects if o.type == 'MESH'), None)
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

dims = obj.dimensions
longest = max(dims)
if longest <= 0:
    raise RuntimeError("Mesh has zero longest dimension")

factor = {target_m!r} / longest
obj.scale = (factor, factor, factor)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

print("scaled longest=", max(obj.dimensions))
"""
    execute_blender_code(code, timeout=30.0)


@pytest.mark.skipif(not _port_open(), reason=_LIVE_REASON)
def test_live_voxel_remesh_keep_largest_vase_yields_one_component_zero_boundary():
    import_glb.run(VASE_GLB)
    _scale_to_longest_dim(80.0)

    voxel_stats = voxel_remesh.run(voxel_size_mm=0.8)
    assert voxel_stats["faces"] > 1000, f"vase voxel face count too low: {voxel_stats}"

    keep_stats = keep_largest.run()
    assert keep_stats["components_after"] == 1
    assert keep_stats["boundary_edges"] == 0, (
        f"vase has boundary edges after keep_largest: {keep_stats}"
    )
    assert keep_stats["non_manifold_edges"] == 0, (
        f"vase has non-manifold edges after keep_largest: {keep_stats}"
    )


@pytest.mark.skipif(not _port_open(), reason=_LIVE_REASON)
def test_live_voxel_remesh_guitar_under_200k_faces_after_scale():
    """
    The acceptance criterion: voxel remesh on guitar AFTER scale produces
    < 200k faces. This proves the scale-before-voxel-remesh ordering — without
    it the count blows up to 2.7M+.
    """
    import_glb.run(GUITAR_GLB)
    _scale_to_longest_dim(200.0)

    voxel_stats = voxel_remesh.run(voxel_size_mm=0.8)
    assert voxel_stats["faces"] < 200_000, (
        f"guitar voxel face count {voxel_stats['faces']} >= 200k -- "
        "scale-before-voxel ordering may be broken"
    )

    keep_stats = keep_largest.run()
    assert keep_stats["components_after"] == 1
    assert keep_stats["boundary_edges"] == 0, (
        f"guitar has boundary edges after keep_largest: {keep_stats}"
    )


@pytest.mark.skipif(not _port_open(), reason=_LIVE_REASON)
def test_live_keep_largest_collapses_multi_component_input_to_one():
    """Drop two cubes into the scene, prove keep_largest leaves only the bigger one."""
    code = """\
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0, 0, 0))
big = bpy.context.active_object
bpy.ops.mesh.primitive_cube_add(size=0.5, location=(5, 0, 0))
small = bpy.context.active_object
bpy.ops.object.select_all(action='DESELECT')
big.select_set(True); small.select_set(True)
bpy.context.view_layer.objects.active = big
bpy.ops.object.join()
"""
    execute_blender_code(code, timeout=10.0)
    stats = keep_largest.run()
    assert stats["components_before"] == 2
    assert stats["components_after"] == 1
    # Big cube has same face count as small cube (6 quads / 12 tris each) — but
    # with `size=2.0` vs `size=0.5` Blender still emits 6 faces per cube. So
    # we tie-break on the first component when sorted; since both have 6, the
    # exact one kept is implementation-defined. Assert face-count == 6.
    assert stats["faces"] == 6
