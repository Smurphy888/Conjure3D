"""
Bambu-compatible 3MF writer (Phase K).

A 3MF file is a ZIP archive with a fixed directory layout. We write the
minimum subset needed for Bambu Studio to open it with:

  - all meshes loaded as separate objects
  - per-object filament-extruder assignments pre-applied (so multi-color
    splits show their colors immediately, no manual filament assignment)
  - a project settings JSON embedded with the user's chosen recipe
    (process, walls, infill, brim, supports, spiral mode), so the user
    just hits "Slice" rather than copying numbers from our recipe panel

Why "minimum subset":

  - The 3MF spec (Microsoft's 3D Manufacturing Format) is broad. We only
    need geometry + materials + Bambu's slicer-config extensions. Other
    optional sections (slice cache, build plate position, thumbnails)
    Bambu generates on first load and doesn't require from us.
  - Schema keys + filenames in Metadata/ are sourced from Bambu Studio's
    OWN written .3mf files (reverse-engineered, well-known in the
    PrusaSlicer/Bambu fork lineage). If a key is misspelled or in the
    wrong file, Bambu silently falls back to its default and the user
    sees the recipe NOT applied — that's the main risk we iterate on
    once the user dogfoods this against a real Bambu install.

Structure produced (zipfile entries, in order):

    [Content_Types].xml          # OPC MIME table — required
    _rels/.rels                  # OPC root relationships — required
    3D/3dmodel.model             # 3MF spec mesh + build
    Metadata/model_settings.config        # Bambu: per-object metadata
    Metadata/project_settings.config      # Bambu: slicer settings (JSON)
    Metadata/slice_info.config            # Bambu: minimal print settings header

Coordinate / unit convention: we store millimetres directly. Blender's
real STL export uses ``global_scale=1000`` to convert from Blender's
unit-less floats; we mirror that here so a chain that yields 80mm in
the STL pipeline yields 80mm in the 3MF pipeline.

Wire format detail: every XML file gets a leading
``<?xml version="1.0" encoding="UTF-8"?>`` declaration with NO BOM —
Bambu's parser rejects UTF-8 BOMs in 3MF members.
"""
from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence


# ── Inputs ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Mesh:
    """One mesh = one object in the 3MF output. ``filament_index`` is the
    1-based slot (matching Bambu's extruder numbering); same mesh may
    share a filament with others (zebra + quarter both share 2 filaments).

    ``color_rgba`` is informational — Bambu primarily uses ``filament_index``
    to pick the colour, but giving the object an explicit material with
    the colour helps when the 3MF is opened in other slicers that don't
    speak Bambu's filament config."""

    name: str
    vertices: Sequence[tuple[float, float, float]]
    triangles: Sequence[tuple[int, int, int]]
    filament_index: int = 1
    color_rgba: tuple[float, float, float, float] = (0.8, 0.1, 0.1, 1.0)


@dataclass(frozen=True)
class RecipeSettings:
    """The slicer recipe baked into project_settings.config. Keep the
    fields in sync with ``sidecar/recipe.py``'s catalogue — that module
    is the single source of truth for which recipe applies to each
    object_type / size."""

    # Process / printer identity. Strings must match Bambu's profile
    # names exactly or Bambu loads its own defaults instead.
    printer_settings_id: str = "Bambu Lab X1 Carbon 0.4 nozzle"
    process_settings_id: str = "0.20mm Standard @BBL X1C"
    layer_height: float = 0.20

    # Walls / shells.
    wall_loops: int = 3
    top_shell_layers: int = 4
    bottom_shell_layers: int = 4

    # Infill.
    sparse_infill_density: int = 15  # percent
    sparse_infill_pattern: str = "gyroid"

    # Adhesion.
    brim_type: str = "outer_only"   # or "no_brim", "outer_and_inner", "auto_brim"
    brim_width: float = 5.0          # mm; ignored if brim_type=no_brim

    # Supports.
    enable_support: bool = False

    # Vase mode.
    spiral_mode: bool = False

    # Filaments. One entry per filament_index used in the mesh list.
    # Lists are length-aligned: filament_colour[0] is the colour of
    # filament_settings_id[0], used by any Mesh with filament_index=1.
    filament_settings_id: list[str] = field(
        default_factory=lambda: ["Bambu PLA Basic"]
    )
    filament_colour: list[str] = field(default_factory=lambda: ["#CC0000"])


# ── Public API ──────────────────────────────────────────────────────────────


def write_3mf(
    meshes: Iterable[Mesh],
    recipe: RecipeSettings,
    dst_path: str | Path,
) -> dict:
    """Write a Bambu-compatible .3mf to ``dst_path``. Overwrites if it
    exists. Returns a structured manifest describing what was written
    (object count, file size, filaments referenced) for the caller's
    log + the JSON-RPC response."""
    mesh_list = list(meshes)
    if not mesh_list:
        raise ValueError("write_3mf: at least one mesh is required")
    if len(recipe.filament_settings_id) != len(recipe.filament_colour):
        raise ValueError(
            "RecipeSettings: filament_settings_id and filament_colour "
            "must have the same length"
        )

    dst = Path(dst_path)
    dst.parent.mkdir(parents=True, exist_ok=True)

    # Object IDs start at 2 — Bambu reserves id=1 for the build plate
    # convention in some templates. Safer to skip 1 entirely.
    id_for: dict[int, int] = {}  # mesh index → 3MF object id
    for i in range(len(mesh_list)):
        id_for[i] = i + 2

    content_types_xml = _build_content_types_xml()
    rels_xml = _build_root_rels_xml()
    model_xml = _build_model_xml(mesh_list, id_for)
    model_settings_xml = _build_model_settings_xml(mesh_list, id_for)
    project_settings_json = _build_project_settings_json(recipe)
    slice_info_xml = _build_slice_info_xml(len(mesh_list))

    # Write with DEFLATE so the file is small. Bambu opens both stored
    # and deflated entries; deflate gets us ~10× compression on XML.
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", rels_xml)
        zf.writestr("3D/3dmodel.model", model_xml)
        zf.writestr("Metadata/model_settings.config", model_settings_xml)
        zf.writestr("Metadata/project_settings.config", project_settings_json)
        zf.writestr("Metadata/slice_info.config", slice_info_xml)

    return {
        "path": str(dst),
        "size": dst.stat().st_size,
        "object_count": len(mesh_list),
        "filament_count": len(set(m.filament_index for m in mesh_list)),
    }


# ── XML builders ────────────────────────────────────────────────────────────
#
# We hand-write the XML rather than reach for xml.etree because:
#   - Output is small and the structure is fixed
#   - Bambu cares about attribute ORDER in some elements (xmlns must come
#     first); ET reorders alphabetically in Python 3.8+
#   - Avoids a UTF-8 BOM that ET sometimes emits
#   - No ns0:/ns1: prefixes (ET adds those even for the default namespace
#     when round-tripped through some writers)


_XML_DECL = '<?xml version="1.0" encoding="UTF-8"?>\n'


def _build_content_types_xml() -> str:
    return _XML_DECL + (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        '  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
        '  <Default Extension="config" ContentType="application/octet-stream"/>\n'
        '</Types>\n'
    )


def _build_root_rels_xml() -> str:
    return _XML_DECL + (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '  <Relationship Id="rel-1" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel" '
        'Target="/3D/3dmodel.model"/>\n'
        '</Relationships>\n'
    )


def _build_model_xml(meshes: list[Mesh], id_for: dict[int, int]) -> str:
    """The actual 3MF mesh document. Vertices in mm, triangles by index.
    A <build> section at the end lists which objects to place on the
    bed (we place all of them, untransformed, sharing the same origin
    — the orchestrator already recenters before export)."""
    out: list[str] = [_XML_DECL]
    out.append(
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">\n'
    )
    out.append("  <resources>\n")
    for i, m in enumerate(meshes):
        oid = id_for[i]
        out.append(f'    <object id="{oid}" type="model">\n')
        out.append("      <mesh>\n")
        out.append("        <vertices>\n")
        for x, y, z in m.vertices:
            # 6 decimal places is enough for sub-micron precision at the
            # scale of 3D-printed objects; tighter precision bloats the
            # file with noise from floating-point rounding.
            out.append(f'          <vertex x="{x:.6f}" y="{y:.6f}" z="{z:.6f}"/>\n')
        out.append("        </vertices>\n")
        out.append("        <triangles>\n")
        for v1, v2, v3 in m.triangles:
            out.append(f'          <triangle v1="{v1}" v2="{v2}" v3="{v3}"/>\n')
        out.append("        </triangles>\n")
        out.append("      </mesh>\n")
        out.append("    </object>\n")
    out.append("  </resources>\n")
    out.append("  <build>\n")
    for i in range(len(meshes)):
        oid = id_for[i]
        # Identity transform — orchestrator's recenter_xy + flat_bottom
        # already positioned the meshes relative to the build plate.
        out.append(f'    <item objectid="{oid}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>\n')
    out.append("  </build>\n")
    out.append("</model>\n")
    return "".join(out)


def _build_model_settings_xml(meshes: list[Mesh], id_for: dict[int, int]) -> str:
    """Bambu's per-object metadata. Most important key here is
    ``extruder`` — it pins each object to a specific filament slot so
    the user doesn't have to right-click-assign in Bambu's UI."""
    out: list[str] = [_XML_DECL]
    out.append("<config>\n")
    for i, m in enumerate(meshes):
        oid = id_for[i]
        out.append(f'  <object id="{oid}">\n')
        out.append(f'    <metadata key="name" value="{_xml_escape(m.name)}"/>\n')
        out.append(f'    <metadata key="extruder" value="{m.filament_index}"/>\n')
        out.append("  </object>\n")
    out.append("</config>\n")
    return "".join(out)


def _build_slice_info_xml(object_count: int) -> str:
    """Minimal slice_info.config. Bambu writes a richer version after
    slicing; for an unsliced-on-output file we only need the placeholder
    so Bambu's loader doesn't choke."""
    return _XML_DECL + (
        '<config>\n'
        '  <header>\n'
        '    <header_item key="X-BBL-Client-Type" value="slicer"/>\n'
        '    <header_item key="X-BBL-Client-Version" value="conjure3d"/>\n'
        '  </header>\n'
        f'  <plate>\n'
        f'    <metadata key="object_count" value="{object_count}"/>\n'
        '  </plate>\n'
        '</config>\n'
    )


# ── JSON builder ────────────────────────────────────────────────────────────


def _build_project_settings_json(recipe: RecipeSettings) -> str:
    """The slicer settings Bambu picks up at load time. Every value is
    a string in Bambu's JSON convention (yes, including integers — the
    PrusaSlicer-derived schema treats config values as strings)."""
    s = recipe
    settings = {
        # Process identity. These names must match Bambu's profile
        # library exactly for the dropdown in Bambu to show them as
        # selected; if not matched, Bambu uses the embedded values
        # anyway (the per-key fields below).
        "printer_settings_id": s.printer_settings_id,
        "process_settings_id": s.process_settings_id,

        # Layers.
        "layer_height": f"{s.layer_height}",
        "initial_layer_print_height": f"{s.layer_height}",

        # Walls / shells.
        "wall_loops": str(s.wall_loops),
        "top_shell_layers": str(s.top_shell_layers),
        "bottom_shell_layers": str(s.bottom_shell_layers),

        # Infill.
        "sparse_infill_density": f"{s.sparse_infill_density}%",
        "sparse_infill_pattern": s.sparse_infill_pattern,

        # Adhesion.
        "brim_type": s.brim_type,
        "brim_width": f"{s.brim_width}",

        # Supports.
        "enable_support": "1" if s.enable_support else "0",

        # Vase mode.
        "spiral_mode": "1" if s.spiral_mode else "0",

        # Filaments. Lists are length-aligned across these three keys —
        # filament_settings_id[i] / filament_colour[i] / filament index
        # (1-based) all refer to the same slot.
        "filament_settings_id": list(s.filament_settings_id),
        "filament_colour": list(s.filament_colour),
    }
    # Sort keys for deterministic output — makes diffs and tests easier.
    return json.dumps(settings, indent=2, sort_keys=True)


# ── helpers ────────────────────────────────────────────────────────────────


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
