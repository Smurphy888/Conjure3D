"""
Vase-only top ops. Pipeline.md § Phase 6 step 8 (gated on object_type).

  open_top         — bisect at z = top - margin, discard the cap above,
                      leaving the vase mouth open.
  bridge_top_loops  — if opening the top produced two boundary loops (outer
                      rim + inner depression rim), bridge them into a single
                      flat lip so the mesh is watertight again.

Both ops are gated on ``object_type``. For anything other than "vase" they
return ``{"skipped": True, ...}`` WITHOUT contacting Blender, so a
solid_decorative mesh is provably left unchanged.
"""
import json

from blender_client import execute_blender_code, DEFAULT_TIMEOUT


VASE = "vase"
DEFAULT_TOP_MARGIN_MM = 2.0  # pipeline.md: bisect at z = top - 2 mm

_RESOLVE_ACTIVE_MESH = """\
obj = bpy.context.view_layer.objects.active
if obj is None or obj.type != 'MESH':
    obj = next((o for o in bpy.context.scene.objects if o.type == 'MESH'), None)
    if obj is None:
        raise RuntimeError("vase_top: no mesh object in scene")
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
"""

# Count boundary edges (edges with exactly one linked face). 0 == watertight.
_BOUNDARY_COUNT = """\
import bmesh
_bm = bmesh.new()
_bm.from_mesh(obj.data)
_bm.edges.ensure_lookup_table()
boundary_edges = sum(1 for e in _bm.edges if len(e.link_faces) == 1)
_bm.free()
"""


def open_top(object_type: str, top_margin_mm: float = DEFAULT_TOP_MARGIN_MM,
             timeout: float = DEFAULT_TIMEOUT) -> dict:
    """
    Bisect the mesh ``top_margin_mm`` below its highest point and discard the
    cap above, leaving the top open.

    Non-vase input is skipped: returns {"skipped": True, "object_type": ...}
    without touching Blender. Vase input returns
    {"skipped": False, "boundary_edges": int, "max_z_mm": float}.
    """
    if object_type != VASE:
        return {"skipped": True, "object_type": object_type}

    if not isinstance(top_margin_mm, (int, float)):
        raise TypeError(
            f"top_margin_mm must be a number, got {type(top_margin_mm).__name__}"
        )
    if top_margin_mm <= 0:
        raise ValueError(f"top_margin_mm must be positive, got {top_margin_mm}")

    margin_m = top_margin_mm / 1000.0

    code = f"""\
import bpy
import json
from mathutils import Vector

{_RESOLVE_ACTIVE_MESH}
corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
max_z = max(v.z for v in corners)
cut_z = max_z - {margin_m!r}

bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
# plane_no points +Z; clear_outer removes the cap above the plane,
# use_fill=False leaves the mouth open.
bpy.ops.mesh.bisect(
    plane_co=(0.0, 0.0, cut_z),
    plane_no=(0.0, 0.0, 1.0),
    clear_inner=False,
    clear_outer=True,
    use_fill=False,
)
bpy.ops.object.mode_set(mode='OBJECT')

{_BOUNDARY_COUNT}
corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
print(json.dumps({{
    "skipped": False,
    "boundary_edges": boundary_edges,
    "max_z_mm": max(v.z for v in corners) * 1000.0,
}}))
"""
    return _last_json(execute_blender_code(code, timeout=timeout))


def bridge_top_loops(object_type: str, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """
    Bridge the open-top boundary loops (outer rim + inner depression rim)
    into a single flat lip, restoring a watertight mesh.

    Non-vase input is skipped (no Blender contact). Vase input returns
    {"skipped": False, "boundary_edges": int, "watertight": bool}.
    """
    if object_type != VASE:
        return {"skipped": True, "object_type": object_type}

    code = f"""\
import bpy
import json

{_RESOLVE_ACTIVE_MESH}
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='DESELECT')
bpy.ops.mesh.select_mode(type='EDGE')
# Boundary edges are non-manifold; select them and bridge the loops.
bpy.ops.mesh.select_non_manifold()
try:
    bpy.ops.mesh.bridge_edge_loops()
except RuntimeError:
    # Fewer than two loops (already closed) — nothing to bridge.
    pass
bpy.ops.object.mode_set(mode='OBJECT')

{_BOUNDARY_COUNT}
print(json.dumps({{
    "skipped": False,
    "boundary_edges": boundary_edges,
    "watertight": boundary_edges == 0,
}}))
"""
    return _last_json(execute_blender_code(code, timeout=timeout))


def _last_json(stdout: str) -> dict:
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            return json.loads(line)
    raise RuntimeError(f"No JSON stats line in op stdout: {stdout!r}")
