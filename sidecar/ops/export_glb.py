"""
Export the whole scene to a .glb. Symmetric with import_glb. Used by the
orchestrator (Issue #22) to write <project>/preview.glb after a chain run.
"""
import json

from blender_client import execute_blender_code, DEFAULT_TIMEOUT


def run(filepath: str, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Returns {"path": filepath, "object_count": int}."""
    if not isinstance(filepath, str):
        raise TypeError(f"filepath must be str, got {type(filepath).__name__}")

    code = f"""\
import bpy
import json

bpy.ops.object.select_all(action='SELECT')
bpy.ops.export_scene.gltf(
    filepath={json.dumps(filepath)},
    export_format='GLB',
    use_selection=True,
)
print(json.dumps({{
    "path": {json.dumps(filepath)},
    "object_count": len([o for o in bpy.context.scene.objects if o.type == 'MESH']),
}}))
"""
    return _last_json(execute_blender_code(code, timeout=timeout))


def _last_json(stdout: str) -> dict:
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            return json.loads(line)
    raise RuntimeError(f"No JSON stats line in op stdout: {stdout!r}")
