"""
3MF export (Phase K).

Extracts every mesh object in the Blender scene, maps each one to its
filament index (via the Conjure_ColorA / Conjure_ColorB / Conjure_Q*_*
naming convention shared with ops/export_stl.py), and writes a Bambu-
compatible .3mf with the recipe baked in.

The geometry extraction runs in Blender; the .3mf file is then written
locally by the sidecar (no need to round-trip the file over the
JSON-RPC socket). This means:

  1. Blender op returns the vertices + triangles + name + filament_index
     for every mesh as JSON (a few hundred KB at most for a 50k-tri
     model after decimate, well within the JSON-RPC budget).
  2. Sidecar builds the RecipeSettings and calls threemf_writer.write_3mf
     locally. Bambu opens the result by path.

Returns ``{"path": str, "size": int, "object_count": int,
"filament_count": int}`` on success. Never raises across the JSON-RPC
boundary — the dispatcher in main.py catches.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from blender_client import execute_blender_code, HEAVY_TIMEOUT
from slugify import slugify
from threemf_writer import Mesh, write_3mf
from recipe import build_recipe, filament_index_for_color


GLOBAL_SCALE_MM = 1000.0  # Blender unit → mm; matches export_stl.py

_QUARTER_RE = re.compile(r"Conjure_Q(\d+)_(\d+)$")


def _color_token(name: str, mode: str) -> str:
    """Same mapping as ops/export_stl.py.color_token — copied here
    rather than imported so the two stay parallel."""
    if mode == "none":
        return ""
    m = _QUARTER_RE.match(name)
    if m:
        band = int(m.group(1))
        return "red" if band == 0 else "yellow"
    if name.startswith("Conjure_ColorA"):
        return "red"
    if name.startswith("Conjure_ColorB"):
        return "yellow"
    return ""


def _stem(slug: str, ts: str) -> str:
    return f"{slugify(slug)}_{slugify(ts, fallback='ts')}"


def run(
    dst_dir: str,
    slug: str,
    ts: str,
    mode: str,
    object_type: str = "solid_decorative",
    longest_mm: float | None = None,
    timeout: float = HEAVY_TIMEOUT,
) -> dict:
    """Export every mesh in the current Blender scene to a single .3mf.

    dst_dir, slug, ts: same as ops/export_stl.run — together they form
                      the output filename.
    mode:             "none" | "zebra" | "quarter"; only used to map
                      mesh names → filament index.
    object_type:      drives the recipe lookup ("vase", "solid_decorative",
                      "flat_part").
    longest_mm:       forwarded to recipe for brim-policy hints.
    """
    if mode not in ("none", "zebra", "quarter"):
        raise ValueError(f"unknown color_split mode: {mode!r}")

    dst_path = Path(dst_dir) / f"{_stem(slug, ts)}.3mf"
    dst_path.parent.mkdir(parents=True, exist_ok=True)

    geometry = _last_json(
        execute_blender_code(_code(mode), timeout=timeout)
    )
    raw_meshes = geometry.get("meshes") or []
    if not raw_meshes:
        raise RuntimeError("export_3mf: no mesh objects in scene")

    meshes: list[Mesh] = []
    for m in raw_meshes:
        token = _color_token(m["name"], mode)
        meshes.append(
            Mesh(
                name=m["name"],
                vertices=[tuple(v) for v in m["vertices"]],
                triangles=[tuple(t) for t in m["triangles"]],
                filament_index=filament_index_for_color(token),
            )
        )

    recipe = build_recipe(
        object_type=object_type,
        longest_mm=longest_mm,
        color_split_mode=mode,
    )

    written = write_3mf(meshes, recipe, dst_path)
    return {
        "mode": mode,
        "object_type": object_type,
        **written,
    }


def _code(mode: str) -> str:
    """Snippet executed inside Blender. Walks every mesh, applies the
    object transform (so the exported coordinates are world-space and
    already-recentered by the orchestrator), and returns vertices +
    triangulated face indices + name. Scale factor (mm) matches
    export_stl.py so a chain that yields 80mm in STL is 80mm in 3MF."""
    return f"""\
import bpy
import json
import bmesh
import mathutils

SCALE = {GLOBAL_SCALE_MM!r}
MODE = {json.dumps(mode)}

meshes_out = []
for o in sorted(
    [o for o in bpy.context.scene.objects if o.type == 'MESH'],
    key=lambda o: o.name,
):
    # Evaluate the object with modifiers so what we export matches
    # what the user sees in the viewport. world_matrix bakes the
    # object's transform into the exported vertex coords (Blender's
    # 3D viewport convention).
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = o.evaluated_get(depsgraph)
    mesh = eval_obj.to_mesh()
    try:
        # Triangulate via bmesh — 3MF only allows triangle faces and
        # the source mesh may have quads / ngons after the
        # orchestrator's chain.
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.triangulate(bm, faces=bm.faces[:])
        bm.to_mesh(mesh)
        bm.free()

        verts = []
        wm = o.matrix_world
        for v in mesh.vertices:
            co = wm @ v.co
            verts.append((co.x * SCALE, co.y * SCALE, co.z * SCALE))
        tris = []
        for p in mesh.polygons:
            # After triangulate, every polygon is a triangle (3 verts).
            vs = p.vertices
            tris.append((vs[0], vs[1], vs[2]))
        meshes_out.append({{
            "name": o.name,
            "vertices": verts,
            "triangles": tris,
        }})
    finally:
        eval_obj.to_mesh_clear()

print(json.dumps({{"mode": MODE, "meshes": meshes_out}}))
"""


def _last_json(stdout: str) -> dict:
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            return json.loads(line)
    raise RuntimeError(f"No JSON line in export_3mf output: {stdout!r}")
