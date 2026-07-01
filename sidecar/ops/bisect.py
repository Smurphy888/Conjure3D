"""
Bisect — cut every mesh in the scene with a single plane, producing two
watertight pieces per input object. Unlike color_split (which assigns
filaments), bisect physically separates the model so the user can print and
assemble the parts.

Chaining: two bisect ops produce 4 pieces (e.g. bisect(z) then bisect(x)
gives top-left, top-right, bottom-left, bottom-right quarters). Each pass
operates on ALL current mesh objects using the combined bounding-box midpoint
as the cut plane, so every piece is cut at the same coordinate as the original.

axis:
  "z" (default) — horizontal plane at mid-height → top half + bottom half
  "x"           — vertical plane → left/right halves
  "y"           — vertical plane → front/back halves

Capping the cut face:
  Each half is bisected with use_fill=False (no auto n-gon), then the open
  boundary is closed with fill_holes(sides=0). fill_holes closes EACH boundary
  loop independently, so a cross-section with several loops (e.g. a character
  cut through two legs) caps correctly — unlike bisect's use_fill, which makes
  a single n-gon and bridges across the gap between loops (the T-junction
  pitfall color_split.py documents). Normals are then recalculated outward so
  the cap faces point the right way.

Sanity contract (see orchestrator):
  A clean cap leaves ZERO boundary edges, so `manifold` stays strict — a bad
  cap correctly shows manifold ✗ rather than being masked. Only
  `single_component` is relaxed when bisect is in the chain, because multiple
  pieces is the intended result.
"""
import json

from blender_client import execute_blender_code, HEAVY_TIMEOUT

Z = "z"
_AXES = ("x", "y", "z")


def run(axis: str = Z, timeout: float = HEAVY_TIMEOUT) -> dict:
    """
    Returns {"objects": <N*2>, "axis": axis, "cut_at_mm": <float>}.

    Operates on ALL mesh objects in the scene so that chained bisects work:
    bisect(z) then bisect(x) → 4 pieces, not 3.

    Raises ValueError for an unknown axis (defence in depth — the schema +
    grammar already constrain it).
    """
    if axis not in _AXES:
        raise ValueError(f"axis must be one of {_AXES}, got {axis!r}")
    return _last_json(execute_blender_code(_code(axis), timeout=timeout))


def _code(axis: str) -> str:
    return f"""\
import bpy
import json
from mathutils import Vector

AXIS = {axis!r}
IDX = {{"x": 0, "y": 1, "z": 2}}[AXIS]

# Collect ALL mesh objects. A prior bisect may have already split the model
# into 2+ pieces; each must be cut so that e.g. bisect(z) then bisect(x)
# yields 4 pieces, not 3 (the bug where only the active half was touched).
meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
if not meshes:
    raise RuntimeError("bisect: no mesh objects in scene")

# Cut plane at the midpoint of the COMBINED bounding box (world space).
# Using the union bbox means an x cut after a z cut still bisects both halves
# at the same lateral midline as the original model.
all_corners = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
lo = min(v[IDX] for v in all_corners)
hi = max(v[IDX] for v in all_corners)
mid = (lo + hi) / 2.0
plane_co = tuple(mid if i == IDX else 0.0 for i in range(3))
plane_no = tuple(1.0 if i == IDX else 0.0 for i in range(3))


def _dup(obj, name):
    d = obj.copy()
    d.data = obj.data.copy()
    bpy.context.collection.objects.link(d)
    d.name = name
    return d


def _half(obj, keep_positive):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    # clear_inner removes the side AGAINST the normal; clear_outer removes the
    # side the normal points toward (matches color_split._slab semantics).
    bpy.ops.mesh.bisect(
        plane_co=plane_co, plane_no=plane_no,
        clear_inner=keep_positive, clear_outer=not keep_positive,
        use_fill=False,
    )
    # Cap each boundary loop independently, then make normals point outward.
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.fill_holes(sides=0)
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode='OBJECT')


result_count = 0
for src in list(meshes):  # snapshot list — scene changes during iteration
    a = _dup(src, src.name + "_A")
    _half(a, keep_positive=True)
    b = _dup(src, src.name + "_B")
    _half(b, keep_positive=False)
    bpy.data.objects.remove(src, do_unlink=True)
    result_count += 2

print(json.dumps({{
    "objects": result_count, "axis": AXIS, "cut_at_mm": mid * 1000.0,
}}))
"""


def _last_json(stdout: str) -> dict:
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            return json.loads(line)
    raise RuntimeError(f"No JSON stats line in op stdout: {stdout!r}")
