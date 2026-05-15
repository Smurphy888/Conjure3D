"""
Fix normal orientation. Pipeline.md § Phase 6 step 6.

Compute the mesh's signed volume; if it is negative the mesh is inside-out
(normals point inward). Flip every normal so the signed volume becomes
positive — outward-pointing normals = positive volume = correct printable
mesh. A mesh that is already correct is left untouched.

Runs after keep_largest/recenter (single watertight component), so the
signed-volume test is meaningful.
"""
import json

from blender_client import execute_blender_code, DEFAULT_TIMEOUT


def run(timeout: float = DEFAULT_TIMEOUT) -> dict:
    """
    Returns {
        "volume_before": float,   # signed, in scene units^3
        "volume_after": float,    # signed; always >= 0 on success
        "flipped": bool,
    }.
    """
    code = """\
import bpy
import bmesh
import json

obj = bpy.context.view_layer.objects.active
if obj is None or obj.type != 'MESH':
    obj = next((o for o in bpy.context.scene.objects if o.type == 'MESH'), None)
    if obj is None:
        raise RuntimeError("fix_normals: no mesh object in scene")
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj


def _signed_volume(mesh):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    v = bm.calc_volume(signed=True)
    bm.free()
    return v


volume_before = _signed_volume(obj.data)

flipped = False
if volume_before < 0:
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.flip_normals()
    bpy.ops.object.mode_set(mode='OBJECT')
    flipped = True

volume_after = _signed_volume(obj.data)

print(json.dumps({
    "volume_before": volume_before,
    "volume_after": volume_after,
    "flipped": flipped,
}))
"""
    return _last_json(execute_blender_code(code, timeout=timeout))


def _last_json(stdout: str) -> dict:
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            return json.loads(line)
    raise RuntimeError(f"No JSON stats line in op stdout: {stdout!r}")
