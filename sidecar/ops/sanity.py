"""
Post-chain sanity measurement. Pipeline.md § Phase 6 sanity checks:
manifold (0 boundary / 0 non-manifold edges), component count, normals
(signed volume > 0), longest dim <= 256 mm.

Aggregates over every mesh object in the scene (color_split leaves several).
"""
import json

from blender_client import execute_blender_code, DEFAULT_TIMEOUT

LONGEST_DIM_LIMIT_MM = 256.0  # pipeline.md sanity bound


def run(timeout: float = DEFAULT_TIMEOUT) -> dict:
    """
    Returns {
        "boundary_edges": int,
        "non_manifold_edges": int,
        "object_count": int,
        "components": int,        # total loose components across all meshes
        "signed_volume": float,   # summed signed volume
        "dims_mm": [x, y, z],     # combined world bbox, mm
    }.
    """
    code = """\
import bpy
import bmesh
import json
from mathutils import Vector

meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
if not meshes:
    raise RuntimeError("sanity: no mesh object in scene")

boundary = 0
non_manifold = 0
components = 0
signed_volume = 0.0
xs, ys, zs = [], [], []

for obj in meshes:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.edges.ensure_lookup_table()
    boundary += sum(1 for e in bm.edges if len(e.link_faces) == 1)
    non_manifold += sum(1 for e in bm.edges if len(e.link_faces) > 2)
    signed_volume += bm.calc_volume(signed=True)

    # Loose-component count via vertex flood fill.
    seen = set()
    comp = 0
    vert_edges = {v.index: [] for v in bm.verts}
    for e in bm.edges:
        vert_edges[e.verts[0].index].append(e.verts[1].index)
        vert_edges[e.verts[1].index].append(e.verts[0].index)
    for vid in vert_edges:
        if vid in seen:
            continue
        comp += 1
        stack = [vid]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(vert_edges[cur])
    components += comp
    bm.free()

    for c in obj.bound_box:
        w = obj.matrix_world @ Vector(c)
        xs.append(w.x); ys.append(w.y); zs.append(w.z)

print(json.dumps({
    "boundary_edges": boundary,
    "non_manifold_edges": non_manifold,
    "object_count": len(meshes),
    "components": components,
    "signed_volume": signed_volume,
    "dims_mm": [
        (max(xs) - min(xs)) * 1000.0,
        (max(ys) - min(ys)) * 1000.0,
        (max(zs) - min(zs)) * 1000.0,
    ],
}))
"""
    return _last_json(execute_blender_code(code, timeout=timeout))


def _last_json(stdout: str) -> dict:
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            return json.loads(line)
    raise RuntimeError(f"No JSON stats line in op stdout: {stdout!r}")
