"""
Keep only the largest connected component (by face count) of the active mesh,
deleting all other loose pieces. Pipeline.md § Phase 6.3.

Returns the kept piece's vertex/face count, the number of components found
before the cull, and basic manifold counters (boundary edges, non-manifold
edges) for the sanity panel.
"""
import json

from blender_client import execute_blender_code, DEFAULT_TIMEOUT


def run(timeout: float = DEFAULT_TIMEOUT) -> dict:
    """
    Returns {
        "vertices": int,
        "faces": int,
        "components_before": int,
        "components_after": 1,
        "boundary_edges": int,
        "non_manifold_edges": int,
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
        raise RuntimeError("keep_largest: no mesh object in scene")
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.separate(type='LOOSE')
bpy.ops.object.mode_set(mode='OBJECT')

components = [o for o in bpy.context.scene.objects if o.type == 'MESH']
components.sort(key=lambda o: len(o.data.polygons), reverse=True)
keeper = components[0]

for o in components[1:]:
    bpy.data.objects.remove(o, do_unlink=True)

bpy.ops.object.select_all(action='DESELECT')
keeper.select_set(True)
bpy.context.view_layer.objects.active = keeper

bm = bmesh.new()
bm.from_mesh(keeper.data)
bm.edges.ensure_lookup_table()
boundary = sum(1 for e in bm.edges if len(e.link_faces) == 1)
non_manifold = sum(1 for e in bm.edges if len(e.link_faces) == 0 or len(e.link_faces) > 2)
bm.free()

print(json.dumps({
    "vertices": len(keeper.data.vertices),
    "faces": len(keeper.data.polygons),
    "components_before": len(components),
    "components_after": 1,
    "boundary_edges": boundary,
    "non_manifold_edges": non_manifold,
}))
"""

    stdout = execute_blender_code(code, timeout=timeout)
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            return json.loads(line)
    raise RuntimeError(f"No JSON stats line in keep_largest output: {stdout!r}")
