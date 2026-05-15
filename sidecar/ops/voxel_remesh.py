"""
Voxel remesh the active mesh at a given voxel size. Welds Meshy's mesh-soup
into a single watertight surface. Pipeline.md § Phase 6.2.

CRITICAL ordering: scale-to-target must run before voxel remesh. Meshy outputs
are at arbitrary scale (often 1-2 m). Voxel remesh on an unscaled mesh at
0.8 mm voxels produces millions of faces. See pipeline.md and HANDOFF.md.

Note: obj.scale alone does not modify mesh-local data. Apply the transform
(`bpy.ops.object.transform_apply(scale=True)`) before this op runs, or the
voxel size sees the original Meshy-scale geometry.
"""
import json

from blender_client import execute_blender_code, HEAVY_TIMEOUT


DEFAULT_VOXEL_SIZE_MM = 0.8


def run(voxel_size_mm: float = DEFAULT_VOXEL_SIZE_MM, timeout: float = HEAVY_TIMEOUT) -> dict:
    """
    Voxel remesh the currently active mesh.

    Returns {"vertices": int, "faces": int, "voxel_size_mm": float}.
    """
    if voxel_size_mm <= 0:
        raise ValueError(f"voxel_size_mm must be positive, got {voxel_size_mm}")

    voxel_size_m = voxel_size_mm / 1000.0

    code = f"""\
import bpy
import json

obj = bpy.context.view_layer.objects.active
if obj is None or obj.type != 'MESH':
    obj = next((o for o in bpy.context.scene.objects if o.type == 'MESH'), None)
    if obj is None:
        raise RuntimeError("voxel_remesh: no mesh object in scene")
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

obj.data.remesh_voxel_size = {voxel_size_m!r}
obj.data.remesh_voxel_adaptivity = 0.0
obj.data.use_remesh_smooth_normals = True
bpy.ops.object.voxel_remesh()

print(json.dumps({{
    "vertices": len(obj.data.vertices),
    "faces": len(obj.data.polygons),
    "voxel_size_mm": {voxel_size_mm!r},
}}))
"""

    stdout = execute_blender_code(code, timeout=timeout)
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            return json.loads(line)
    raise RuntimeError(f"No JSON stats line in voxel_remesh output: {stdout!r}")
