"""
Phase 7 STL export (pipeline.md § Phase 7 / ISSUES.md #24).

Binary STL, millimetre units (``global_scale=1000``), one file per output
mesh object, named per the file-stem convention:

  none mode    : ``<slug>_<ts>.stl``                          (1 file)
  zebra mode   : ``<slug>_<ts>_red.stl``, ``..._yellow.stl``  (2 files)
  quarter mode : ``<slug>_<ts>_red-q0.stl`` … ``_yellow-q3``  (8 files)

Color tokens are derived from the object names ``color_split`` assigns
(``Conjure_ColorA`` / ``Conjure_ColorB`` for zebra; ``Conjure_Q{band}_{wedge}``
for quarter). Band 0 = red, band 1 = yellow — matching ``color_split``'s
``MAT_RED`` / ``MAT_YELLOW`` band-assignment order. ``none`` mode exports the
single mesh under the bare stem with no color suffix regardless of its name.

Blender 4.2+ uses the core ``bpy.ops.wm.stl_export`` (the legacy add-on
``bpy.ops.export_mesh.stl`` is deprecated and uses different kwarg names —
do NOT cross-pollinate ``use_mesh_modifiers`` / ``use_selection`` here). One
object is selected per call with ``export_selected_objects=True`` so each
object lands in its own file. ``forward_axis='Y'`` / ``up_axis='Z'`` are
pinned explicitly: the new exporter changed defaults in some 4.2.x point
releases and a mismatch silently rotates the STL (slicer loads it sideways).

slug and ts are both run through ``slugify()`` so the on-disk names are
guaranteed Windows-legal (a raw ``HH:MM:SS`` timestamp's ``:`` would break
Blender's file IO). Paths are templated into the Blender snippet via
``json.dumps`` so an apostrophe in the working directory is safe.

Standalone op. Wiring it into ``orchestrator.apply_chain`` is left for
Issue #25 (slicer.launch) so the existing chain-result shape stays stable —
see the Issue #24 commit body for the decision future-fire-you must make.
"""
import json
import os
import re

from blender_client import execute_blender_code, HEAVY_TIMEOUT
from slugify import slugify

NONE = "none"
ZEBRA = "zebra"
QUARTER = "quarter"
_MODES = (NONE, ZEBRA, QUARTER)

GLOBAL_SCALE_MM = 1000.0

# How many STL files each mode must produce. Used to fail the live run
# legibly if Blender hands back the wrong object set.
EXPECTED_COUNT = {NONE: 1, ZEBRA: 2, QUARTER: 8}


_QUARTER_RE = re.compile(r"Conjure_Q(\d+)_(\d+)$")


def color_token(name: str, mode: str) -> str:
    """Canonical object-name → filename color token map. The Blender snippet
    in ``_code`` embeds an identical copy (it runs in Blender's interpreter,
    not here); keep the two in sync — ``test_export_stl`` asserts the snippet
    still contains the same patterns.

    ``none`` → always ``""`` (bare stem). For split modes, an object whose
    name matches no Conjure_* pattern also yields ``""``.
    """
    if mode == NONE:
        return ""
    m = _QUARTER_RE.match(name)
    if m:
        band, wedge = int(m.group(1)), int(m.group(2))
        return ("red" if band == 0 else "yellow") + "-q" + str(wedge)
    if name.startswith("Conjure_ColorA"):
        return "red"
    if name.startswith("Conjure_ColorB"):
        return "yellow"
    return ""


def _stem(slug: str, ts: str) -> str:
    """``<slug>_<ts>`` with each half slugified independently so the joining
    underscore survives (slugify would otherwise turn it into a dash)."""
    return f"{slugify(slug)}_{slugify(ts, fallback='ts')}"


def run(dst_dir: str, slug: str, ts: str, mode: str,
        timeout: float = HEAVY_TIMEOUT) -> dict:
    """
    Export every mesh object in the scene to its own binary STL in
    ``dst_dir`` (created if absent).

    Returns::

        {"mode": mode, "dir": dst_dir, "count": int,
         "files": [{"path": str, "color": str, "size": int}, ...]}

    Raises ``ValueError`` for an unknown mode and ``RuntimeError`` if the
    number of files written does not match ``EXPECTED_COUNT[mode]``.
    """
    if mode not in _MODES:
        raise ValueError(f"mode must be one of {_MODES}, got {mode!r}")
    for label, val in (("dst_dir", dst_dir), ("slug", slug), ("ts", ts)):
        if not isinstance(val, str):
            raise TypeError(f"{label} must be str, got {type(val).__name__}")

    os.makedirs(dst_dir, exist_ok=True)
    stem = _stem(slug, ts)

    result = _last_json(
        execute_blender_code(_code(dst_dir, stem, mode), timeout=timeout)
    )

    want = EXPECTED_COUNT[mode]
    got = result.get("count")
    if got != want:
        raise RuntimeError(
            f"{mode} export expected {want} STL file(s), got {got}: "
            f"{[f.get('path') for f in result.get('files', [])]}"
        )
    return result


def _code(dst_dir: str, stem: str, mode: str) -> str:
    return f"""\
import bpy
import json
import os
import re

DST = {json.dumps(dst_dir)}
STEM = {json.dumps(stem)}
MODE = {json.dumps(mode)}


def color_token(name):
    if MODE == "none":
        return ""
    m = re.match(r"Conjure_Q(\\d+)_(\\d+)$", name)
    if m:
        band, wedge = int(m.group(1)), int(m.group(2))
        return ("red" if band == 0 else "yellow") + "-q" + str(wedge)
    if name.startswith("Conjure_ColorA"):
        return "red"
    if name.startswith("Conjure_ColorB"):
        return "yellow"
    return ""


meshes = sorted(
    [o for o in bpy.context.scene.objects if o.type == 'MESH'],
    key=lambda o: o.name,
)
if not meshes:
    raise RuntimeError("export_stl: no mesh object in scene")

files = []
for o in meshes:
    tok = color_token(o.name)
    fname = STEM + (("_" + tok) if tok else "") + ".stl"
    fpath = os.path.join(DST, fname)

    bpy.ops.object.select_all(action='DESELECT')
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    bpy.ops.wm.stl_export(
        filepath=fpath,
        ascii_format=False,
        export_selected_objects=True,
        global_scale={GLOBAL_SCALE_MM!r},
        apply_modifiers=True,
        forward_axis='Y',
        up_axis='Z',
    )

    size = os.path.getsize(fpath)
    if size == 0:
        raise RuntimeError("export_stl: empty STL written: " + fpath)
    with open(fpath, 'rb') as fh:
        head = fh.read(5)
    if head[:5].lower() == b'solid':
        raise RuntimeError("export_stl: STL is ASCII not binary: " + fpath)

    files.append({{"path": fpath, "color": tok, "size": size}})

print(json.dumps({{
    "mode": MODE, "dir": DST, "count": len(files), "files": files,
}}))
"""


def _last_json(stdout: str) -> dict:
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            return json.loads(line)
    raise RuntimeError(f"No JSON stats line in op stdout: {stdout!r}")
