"""
Separate loose — split every mesh object into its disconnected geometry islands.

Meshy character exports commonly bundle head, torso, arms, and legs as loose
(non-touching) sub-meshes inside a single object. This op calls Blender's
``mesh.separate(type='LOOSE')`` on each mesh in the scene, turning N loose
parts into N separate, individually named objects.

Caveats:
  * Works only when the source mesh has truly disconnected islands. If the
    model is one seamless mesh (arms welded to torso) this produces 1 object
    — the same as the input.
  * Do NOT combine with voxel_remesh in the same chain: voxel_remesh merges
    all loose islands into one solid blob BEFORE separate_loose can split them
    (canonical order puts separate_loose at slot 2, voxel_remesh at slot 3,
    so voxel_remesh would run after and re-merge the parts). If the model
    needs to be watertight per-part, apply the chain in two passes: separate
    first, then remesh each exported part individually.

Sanity contract (see orchestrator):
  Multiple components is the intended result; ``single_component`` and
  ``manifold`` are both relaxed when this op is in the chain, because the
  parts may share seam edges at their former join lines.
"""
import json

from blender_client import execute_blender_code, HEAVY_TIMEOUT


def run(timeout: float = HEAVY_TIMEOUT) -> dict:
    """
    Returns {"objects": <after_count>, "from_count": <before_count>}.
    """
    return _last_json(execute_blender_code(_code(), timeout=timeout))


def _code() -> str:
    return """\
import bpy
import json

meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
if not meshes:
    raise RuntimeError("separate_loose: no mesh objects in scene")

before_count = len(meshes)

for src in list(meshes):  # snapshot — scene changes during iteration
    bpy.ops.object.select_all(action='DESELECT')
    src.select_set(True)
    bpy.context.view_layer.objects.active = src
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.separate(type='LOOSE')
    bpy.ops.object.mode_set(mode='OBJECT')

after_count = len([o for o in bpy.context.scene.objects if o.type == 'MESH'])

print(json.dumps({"objects": after_count, "from_count": before_count}))
"""


def _last_json(stdout: str) -> dict:
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            return json.loads(line)
    raise RuntimeError(f"No JSON stats line in op stdout: {stdout!r}")
