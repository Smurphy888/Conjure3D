"""
Color split — the optional last Phase-6 step. Pipeline.md § Phase 6 step 9.

Modes:
  none     — no split; returns {"skipped": True} WITHOUT contacting Blender.
  zebra    — bisect the mesh into N horizontal bands, alternate red/yellow,
             then group all bands of each color into one object -> 2 objects.
  quarter  — 2-band zebra alternation, each band quartered into 4 angular
             wedges via Boolean INTERSECT (EXACT solver) -> 8 objects.

Spec disambiguation (quarter): pipeline.md says "4 wedge sets per color" and
ISSUES.md #21 says "4 wedges per color (8 outputs)". Read as 4 angular wedges
x 2 alternating colors = 8 output meshes. Documented here so a live-test
mismatch is cheap to reconcile.

HANDOFF pitfall: `bisect ... use_fill=True` makes T-junction artifacts on
*multi-component* meshes, and color quartering must use Boolean Intersect
EXACT. color_split runs LAST (after keep_largest), so its input is a single
component: zebra's per-band duplicate + double-bisect is safe, and quarter
uses Boolean INTERSECT EXACT exactly as HANDOFF prescribes.

Acceptance #3 of ISSUES.md #21 ("Editor warning when object_type != vase")
is already implemented + tested in the frontend (src/lib/edits.ts
shouldWarnColorSplit, 17 passing vitest cases) — this module is backend-only.
"""
import json

from blender_client import execute_blender_code, HEAVY_TIMEOUT


NONE = "none"
ZEBRA = "zebra"
QUARTER = "quarter"
_MODES = (NONE, ZEBRA, QUARTER)

DEFAULT_ZEBRA_COUNT = 8

# Resolve target mesh and create the two shared materials.
_PREAMBLE = """\
import bpy
import json
from mathutils import Vector

src = bpy.context.view_layer.objects.active
if src is None or src.type != 'MESH':
    src = next((o for o in bpy.context.scene.objects if o.type == 'MESH'), None)
    if src is None:
        raise RuntimeError("color_split: no mesh object in scene")
bpy.ops.object.select_all(action='DESELECT')
src.select_set(True)
bpy.context.view_layer.objects.active = src


def _mat(name, rgba):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.diffuse_color = rgba
    return m


MAT_RED = _mat("Conjure_Red", (0.80, 0.10, 0.10, 1.0))
MAT_YELLOW = _mat("Conjure_Yellow", (0.95, 0.85, 0.10, 1.0))


def _assign(obj, mat):
    obj.data.materials.clear()
    obj.data.materials.append(mat)


def _world_bounds(obj):
    cs = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    return (min(v.z for v in cs), max(v.z for v in cs),
            min(v.x for v in cs), max(v.x for v in cs),
            min(v.y for v in cs), max(v.y for v in cs))


def _dup(obj):
    d = obj.copy()
    d.data = obj.data.copy()
    bpy.context.collection.objects.link(d)
    return d


def _slab(obj, z_lo, z_hi):
    \"\"\"Trim obj to the [z_lo, z_hi] band with two capped bisects.\"\"\"
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.bisect(plane_co=(0.0, 0.0, z_lo), plane_no=(0.0, 0.0, 1.0),
                        clear_inner=True, clear_outer=False, use_fill=True)
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.bisect(plane_co=(0.0, 0.0, z_hi), plane_no=(0.0, 0.0, 1.0),
                        clear_inner=False, clear_outer=True, use_fill=True)
    bpy.ops.object.mode_set(mode='OBJECT')


def _join(objs, name):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    joined = bpy.context.view_layer.objects.active
    joined.name = name
    return joined
"""


def run(mode: str, count: int = DEFAULT_ZEBRA_COUNT,
        timeout: float = HEAVY_TIMEOUT) -> dict:
    """
    Returns, for mode ``none``:   {"skipped": True, "mode": "none"}
            for mode ``zebra``:  {"skipped": False, "mode": "zebra",
                                   "objects": 2, "bands": count}
            for mode ``quarter``:{"skipped": False, "mode": "quarter",
                                   "objects": 8, "bands": 2,
                                   "wedges_per_band": 4}
    """
    if mode not in _MODES:
        raise ValueError(f"mode must be one of {_MODES}, got {mode!r}")

    if mode == NONE:
        return {"skipped": True, "mode": NONE}

    if mode == ZEBRA:
        if not isinstance(count, int) or isinstance(count, bool):
            raise TypeError(f"count must be an int, got {type(count).__name__}")
        if count < 2:
            raise ValueError(f"zebra count must be >= 2, got {count}")
        return _last_json(execute_blender_code(_zebra_code(count), timeout=timeout))

    # QUARTER
    return _last_json(execute_blender_code(_quarter_code(), timeout=timeout))


def _zebra_code(count: int) -> str:
    return f"""\
{_PREAMBLE}
N = {count!r}
zmin, zmax, *_ = _world_bounds(src)
band_h = (zmax - zmin) / N

bands = []
for i in range(N):
    d = _dup(src)
    _slab(d, zmin + i * band_h, zmin + (i + 1) * band_h)
    _assign(d, MAT_RED if i % 2 == 0 else MAT_YELLOW)
    bands.append(d)

bpy.data.objects.remove(src, do_unlink=True)
red = _join([b for i, b in enumerate(bands) if i % 2 == 0], "Conjure_ColorA")
yellow = _join([b for i, b in enumerate(bands) if i % 2 == 1], "Conjure_ColorB")

print(json.dumps({{
    "skipped": False, "mode": "zebra", "objects": 2, "bands": N,
}}))
"""


def _quarter_code() -> str:
    return f"""\
{_PREAMBLE}
zmin, zmax, xmin, xmax, ymin, ymax = _world_bounds(src)
mid_z = (zmin + zmax) / 2.0
span = max(xmax - xmin, ymax - ymin, zmax - zmin) * 4.0 + 1.0


def _cutter(name, sx, sy):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(sx * span / 2.0,
                                                        sy * span / 2.0,
                                                        (zmin + zmax) / 2.0))
    c = bpy.context.active_object
    c.name = name
    c.scale = (span, span, span)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return c


# Four cutter cubes, one per XY quadrant (centered on the world origin, since
# recenter_xy already put the bbox center at X=0,Y=0).
cutters = [_cutter("cut_pp", 1, 1), _cutter("cut_np", -1, 1),
           _cutter("cut_nn", -1, -1), _cutter("cut_pn", 1, -1)]

outputs = []
# Two alternating-color horizontal bands.
for bi, (z_lo, z_hi, mat) in enumerate((
        (zmin, mid_z, MAT_RED), (mid_z, zmax, MAT_YELLOW))):
    band = _dup(src)
    _slab(band, z_lo, z_hi)
    for qi, cutter in enumerate(cutters):
        wedge = _dup(band)
        m = wedge.modifiers.new(name="qcut", type='BOOLEAN')
        m.operation = 'INTERSECT'
        m.solver = 'EXACT'
        m.object = cutter
        bpy.ops.object.select_all(action='DESELECT')
        wedge.select_set(True)
        bpy.context.view_layer.objects.active = wedge
        bpy.ops.object.modifier_apply(modifier=m.name)
        _assign(wedge, mat)
        wedge.name = f"Conjure_Q{{bi}}_{{qi}}"
        outputs.append(wedge)
    bpy.data.objects.remove(band, do_unlink=True)

for c in cutters:
    bpy.data.objects.remove(c, do_unlink=True)
bpy.data.objects.remove(src, do_unlink=True)

print(json.dumps({{
    "skipped": False, "mode": "quarter", "objects": len(outputs),
    "bands": 2, "wedges_per_band": 4,
}}))
"""


def _last_json(stdout: str) -> dict:
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            return json.loads(line)
    raise RuntimeError(f"No JSON stats line in op stdout: {stdout!r}")
