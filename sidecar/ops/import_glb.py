"""
Reset the Blender scene and import a .glb / .gltf. Joins multiple imported
meshes into one and leaves it as the active+selected object.

Used as the entry point for every downstream geometry op test, and by the
orchestrator (Issue #22) for Phase 5 of pipeline.md.
"""
import json

from blender_client import execute_blender_code, DEFAULT_TIMEOUT


def run(filepath: str, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """
    Returns {"vertices": int, "faces": int, "object_count": int}.
    object_count is always 1 after a successful import — multiple imported
    meshes are joined.
    """
    if not isinstance(filepath, str):
        raise TypeError(f"filepath must be str, got {type(filepath).__name__}")

    code = f"""\
import bpy
import json

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath={json.dumps(filepath)})

mesh_objects = [o for o in bpy.context.scene.objects if o.type == 'MESH']
if not mesh_objects:
    raise RuntimeError("GLB import produced no mesh")

if len(mesh_objects) > 1:
    bpy.ops.object.select_all(action='DESELECT')
    for o in mesh_objects:
        o.select_set(True)
    bpy.context.view_layer.objects.active = mesh_objects[0]
    bpy.ops.object.join()

active = next(o for o in bpy.context.scene.objects if o.type == 'MESH')
bpy.ops.object.select_all(action='DESELECT')
active.select_set(True)
bpy.context.view_layer.objects.active = active

print(json.dumps({{
    "vertices": len(active.data.vertices),
    "faces": len(active.data.polygons),
    "object_count": 1,
}}))
"""

    stdout = execute_blender_code(code, timeout=timeout)
    return _last_json(stdout)


def _last_json(stdout: str) -> dict:
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            return json.loads(line)
    raise RuntimeError(f"No JSON stats line in op stdout: {stdout!r}")
