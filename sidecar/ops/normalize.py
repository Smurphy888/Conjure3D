"""
Phase 6 normalization ops: scale-to-longest-dim, recenter X/Y + base-to-z=0,
and flat-bottom. Pipeline.md § Phase 6 steps 1, 4, 5.

Scene/mesh units are metres (matches voxel_remesh, which sends a metre voxel
size). All public params are in millimetres and converted to metres before
they reach Blender.

Strict pipeline ordering (pipeline.md):
  scale_to_longest → voxel_remesh → keep_largest → recenter_xy → flat_bottom

scale_to_longest MUST run before voxel remesh — Meshy outputs are at arbitrary
scale (often 1–2 m); voxel remesh on an unscaled mesh produces millions of
faces (see HANDOFF.md). flat_bottom runs after keep_largest, so the mesh is a
single component and bisect-with-fill is safe here (the multi-component
T-junction pitfall in HANDOFF.md applies only to color quartering).
"""
import json

from blender_client import execute_blender_code, DEFAULT_TIMEOUT


DEFAULT_FLAT_BOTTOM_CUT_MM = 0.8  # within pipeline.md's 0.5–1 mm window

# Shared preamble: resolve the mesh to operate on (active, else first mesh in
# scene) and make it the sole active+selected object. Same fallback contract
# as the other ops modules.
_RESOLVE_ACTIVE_MESH = """\
obj = bpy.context.view_layer.objects.active
if obj is None or obj.type != 'MESH':
    obj = next((o for o in bpy.context.scene.objects if o.type == 'MESH'), None)
    if obj is None:
        raise RuntimeError("normalize: no mesh object in scene")
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
"""


def scale_to_longest(target_mm: float, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """
    Uniformly scale the active mesh so its longest world-space bbox dimension
    equals ``target_mm``. Bakes the result into mesh-local data so downstream
    voxel remesh sees the scaled geometry.

    Returns {"longest_mm": float, "dimensions_mm": [x, y, z], "factor": float}.
    """
    if not isinstance(target_mm, (int, float)):
        raise TypeError(f"target_mm must be a number, got {type(target_mm).__name__}")
    if target_mm <= 0:
        raise ValueError(f"target_mm must be positive, got {target_mm}")

    target_m = target_mm / 1000.0

    code = f"""\
import bpy
import json

{_RESOLVE_ACTIVE_MESH}
# Bake any incoming rotation/scale so dimensions reflect real geometry.
bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

longest = max(obj.dimensions)
if longest <= 0:
    raise RuntimeError("scale_to_longest: mesh has zero longest dimension")

factor = {target_m!r} / longest
obj.scale = (factor, factor, factor)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

d = obj.dimensions
print(json.dumps({{
    "longest_mm": max(d) * 1000.0,
    "dimensions_mm": [d.x * 1000.0, d.y * 1000.0, d.z * 1000.0],
    "factor": factor,
}}))
"""
    return _last_json(execute_blender_code(code, timeout=timeout))


def recenter_xy(timeout: float = DEFAULT_TIMEOUT) -> dict:
    """
    Translate the active mesh so its world-space bounding box is centred on
    X=0 and Y=0, with its base sitting on z=0. Bakes the translation into
    mesh-local data. Pipeline.md § Phase 6 step 4.

    Returns {"center_x_mm": float, "center_y_mm": float, "min_z_mm": float}
    measured AFTER the move (all should be ~0).
    """
    code = f"""\
import bpy
import json
from mathutils import Vector

{_RESOLVE_ACTIVE_MESH}
corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
xs = [v.x for v in corners]
ys = [v.y for v in corners]
zs = [v.z for v in corners]
center_x = (min(xs) + max(xs)) / 2.0
center_y = (min(ys) + max(ys)) / 2.0
min_z = min(zs)

obj.location.x -= center_x
obj.location.y -= center_y
obj.location.z -= min_z
bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)

corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
xs = [v.x for v in corners]
ys = [v.y for v in corners]
zs = [v.z for v in corners]
print(json.dumps({{
    "center_x_mm": ((min(xs) + max(xs)) / 2.0) * 1000.0,
    "center_y_mm": ((min(ys) + max(ys)) / 2.0) * 1000.0,
    "min_z_mm": min(zs) * 1000.0,
}}))
"""
    return _last_json(execute_blender_code(code, timeout=timeout))


def flat_bottom(cut_mm: float = DEFAULT_FLAT_BOTTOM_CUT_MM,
                timeout: float = DEFAULT_TIMEOUT) -> dict:
    """
    Bisect the (single-component) mesh at z=``cut_mm``, discard everything
    below, fill the cut into a flat base, then drop the result back to z=0.
    Removes sub-mm tails on the base. Pipeline.md § Phase 6 step 5.

    Must run after keep_largest (single component) so bisect-with-fill does
    not create the multi-component T-junctions noted in HANDOFF.md.

    Returns {"min_z_mm": float, "max_z_mm": float, "cut_mm": float} measured
    AFTER repositioning (min_z_mm should be ~0).
    """
    if not isinstance(cut_mm, (int, float)):
        raise TypeError(f"cut_mm must be a number, got {type(cut_mm).__name__}")
    if cut_mm <= 0:
        raise ValueError(f"cut_mm must be positive, got {cut_mm}")

    cut_m = cut_mm / 1000.0

    code = f"""\
import bpy
import json
from mathutils import Vector

{_RESOLVE_ACTIVE_MESH}
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
# plane_no points +Z; clear_inner removes the back (below-plane) side.
bpy.ops.mesh.bisect(
    plane_co=(0.0, 0.0, {cut_m!r}),
    plane_no=(0.0, 0.0, 1.0),
    clear_inner=True,
    clear_outer=False,
    use_fill=True,
)
bpy.ops.object.mode_set(mode='OBJECT')

# After the cut the new base sits at z=cut_m; drop it back to z=0.
corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
min_z = min(v.z for v in corners)
obj.location.z -= min_z
bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)

corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
zs = [v.z for v in corners]
print(json.dumps({{
    "min_z_mm": min(zs) * 1000.0,
    "max_z_mm": max(zs) * 1000.0,
    "cut_mm": {cut_mm!r},
}}))
"""
    return _last_json(execute_blender_code(code, timeout=timeout))


def _last_json(stdout: str) -> dict:
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            return json.loads(line)
    raise RuntimeError(f"No JSON stats line in op stdout: {stdout!r}")
