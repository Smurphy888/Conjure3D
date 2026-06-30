"""
Decimate to a target face count. Pipeline.md § Phase 6 step 7.

Voxel remesh always overproduces geometry; a COLLAPSE decimate modifier
brings the face count back down so STLs stay sane. The modifier works on a
ratio (0..1); we derive it from the current face count and the requested
target. Meshes already at or under target are left untouched (ratio 1.0).

For voxel-remeshed inputs the effective ratio is typically < 0.1.
"""
import json

from blender_client import execute_blender_code, HEAVY_TIMEOUT


DEFAULT_TARGET_FACES = 50_000  # pipeline.md default


def run(target_faces: int = DEFAULT_TARGET_FACES, timeout: float = HEAVY_TIMEOUT) -> dict:
    """
    Returns {
        "faces_before": int,
        "faces_after": int,
        "target_faces": int,
        "ratio": float,        # decimate ratio actually applied (1.0 = no-op)
    }.
    """
    if not isinstance(target_faces, int) or isinstance(target_faces, bool):
        raise TypeError(
            f"target_faces must be an int, got {type(target_faces).__name__}"
        )
    if target_faces <= 0:
        raise ValueError(f"target_faces must be positive, got {target_faces}")

    code = f"""\
import bpy
import json

obj = bpy.context.view_layer.objects.active
if obj is None or obj.type != 'MESH':
    obj = next((o for o in bpy.context.scene.objects if o.type == 'MESH'), None)
    if obj is None:
        raise RuntimeError("decimate: no mesh object in scene")
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj

target = {target_faces!r}
faces_before = len(obj.data.polygons)

if faces_before > target:
    ratio = target / faces_before
    mod = obj.modifiers.new(name="Decimate", type='DECIMATE')
    mod.decimate_type = 'COLLAPSE'
    mod.ratio = ratio
    bpy.ops.object.modifier_apply(modifier=mod.name)
else:
    ratio = 1.0

faces_after = len(obj.data.polygons)
print(json.dumps({{
    "faces_before": faces_before,
    "faces_after": faces_after,
    "target_faces": target,
    "ratio": ratio,
}}))
"""
    return _last_json(execute_blender_code(code, timeout=timeout))


def _last_json(stdout: str) -> dict:
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            return json.loads(line)
    raise RuntimeError(f"No JSON stats line in op stdout: {stdout!r}")
