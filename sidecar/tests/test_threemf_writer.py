"""
Tests for threemf_writer.py + recipe.py (Phase K).

Two layers:

  1. Writer structure: the .3mf is a valid ZIP, contains every required
     OPC/3MF entry, the XML parses, the embedded vertex/triangle counts
     match what we passed in, the model_settings.config has one entry
     per object with the right extruder index, project_settings.config
     is valid JSON containing the recipe.

  2. Recipe lookup: each object_type produces the documented set of
     settings; color_split_mode controls filament count.

We don't (cannot) test "does it actually open in Bambu Studio" from
here — that's the user-facing dogfood gate. What we CAN do is enforce
structural correctness end-to-end so when Bambu rejects something,
the cause is unambiguously a schema mismatch (the structure was
correct; Bambu wants a different key name) rather than a packaging bug.
"""
import json
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from threemf_writer import Mesh, RecipeSettings, write_3mf  # noqa: E402
from recipe import (  # noqa: E402
    build_recipe,
    filament_index_for_color,
    COLOR_RED_HEX,
    COLOR_YELLOW_HEX,
)


# ── Test fixtures ───────────────────────────────────────────────────────────


def _cube_mesh(name: str, filament_index: int = 1) -> Mesh:
    """Tiny mesh fixture: a unit cube. 8 vertices, 12 triangles."""
    v = [
        (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.0, 1.0, 1.0),
    ]
    t = [
        (0, 1, 2), (0, 2, 3),   # bottom
        (4, 6, 5), (4, 7, 6),   # top
        (0, 4, 5), (0, 5, 1),   # front
        (1, 5, 6), (1, 6, 2),   # right
        (2, 6, 7), (2, 7, 3),   # back
        (3, 7, 4), (3, 4, 0),   # left
    ]
    return Mesh(name=name, vertices=v, triangles=t, filament_index=filament_index)


# ── Writer structure ────────────────────────────────────────────────────────


def test_writes_a_valid_zip(tmp_path: Path):
    dst = tmp_path / "out.3mf"
    write_3mf([_cube_mesh("Cube")], RecipeSettings(), dst)
    assert dst.is_file()
    assert dst.stat().st_size > 0
    assert zipfile.is_zipfile(dst)


def test_zip_contains_every_required_entry(tmp_path: Path):
    """Every entry in this list is required for Bambu to recognise the
    archive as a 3MF and to apply the embedded settings. Missing any
    one is a silent fallback to defaults."""
    dst = tmp_path / "out.3mf"
    write_3mf([_cube_mesh("Cube")], RecipeSettings(), dst)
    with zipfile.ZipFile(dst) as zf:
        names = set(zf.namelist())
    required = {
        "[Content_Types].xml",
        "_rels/.rels",
        "3D/3dmodel.model",
        "Metadata/model_settings.config",
        "Metadata/project_settings.config",
        "Metadata/slice_info.config",
    }
    missing = required - names
    assert not missing, f"missing required entries: {missing}"


def test_xml_entries_parse(tmp_path: Path):
    """Every XML member must be well-formed. A single misplaced quote
    in the writer would let the test suite go green while Bambu's
    parser barfs at load time — catch that here."""
    dst = tmp_path / "out.3mf"
    write_3mf([_cube_mesh("A"), _cube_mesh("B", filament_index=2)],
              RecipeSettings(), dst)
    with zipfile.ZipFile(dst) as zf:
        for name in (
            "[Content_Types].xml",
            "_rels/.rels",
            "3D/3dmodel.model",
            "Metadata/model_settings.config",
            "Metadata/slice_info.config",
        ):
            data = zf.read(name)
            ET.fromstring(data)  # raises on malformed XML


def test_model_xml_has_correct_object_and_triangle_counts(tmp_path: Path):
    dst = tmp_path / "out.3mf"
    write_3mf([_cube_mesh("A"), _cube_mesh("B")], RecipeSettings(), dst)
    with zipfile.ZipFile(dst) as zf:
        xml = zf.read("3D/3dmodel.model")
    root = ET.fromstring(xml)
    ns = {"c": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    objects = root.findall("c:resources/c:object", ns)
    assert len(objects) == 2
    for obj in objects:
        verts = obj.findall("c:mesh/c:vertices/c:vertex", ns)
        tris = obj.findall("c:mesh/c:triangles/c:triangle", ns)
        assert len(verts) == 8     # _cube_mesh: 8 verts
        assert len(tris) == 12     # _cube_mesh: 12 tris
    items = root.findall("c:build/c:item", ns)
    assert len(items) == 2


def test_model_settings_assigns_each_object_to_its_filament(tmp_path: Path):
    """The .3mf's per-object extruder metadata must match each Mesh's
    filament_index, or Bambu will show every object on filament 1."""
    dst = tmp_path / "out.3mf"
    write_3mf(
        [_cube_mesh("A", filament_index=1), _cube_mesh("B", filament_index=2)],
        RecipeSettings(filament_settings_id=["Bambu PLA Basic", "Bambu PLA Basic"],
                       filament_colour=[COLOR_RED_HEX, COLOR_YELLOW_HEX]),
        dst,
    )
    with zipfile.ZipFile(dst) as zf:
        xml = zf.read("Metadata/model_settings.config")
    root = ET.fromstring(xml)
    objs = root.findall("object")
    assert len(objs) == 2
    extruders = []
    for obj in objs:
        for meta in obj.findall("metadata"):
            if meta.get("key") == "extruder":
                extruders.append(meta.get("value"))
    assert sorted(extruders) == ["1", "2"]


def test_project_settings_is_valid_json_with_recipe_fields(tmp_path: Path):
    dst = tmp_path / "out.3mf"
    recipe = RecipeSettings(
        wall_loops=5,
        sparse_infill_density=0,
        spiral_mode=True,
        brim_type="no_brim",
    )
    write_3mf([_cube_mesh("V")], recipe, dst)
    with zipfile.ZipFile(dst) as zf:
        raw = zf.read("Metadata/project_settings.config")
    data = json.loads(raw)
    assert data["wall_loops"] == "5"
    assert data["sparse_infill_density"] == "0%"
    assert data["spiral_mode"] == "1"
    assert data["brim_type"] == "no_brim"


# ── Input validation ────────────────────────────────────────────────────────


def test_write_3mf_requires_at_least_one_mesh(tmp_path: Path):
    with pytest.raises(ValueError):
        write_3mf([], RecipeSettings(), tmp_path / "x.3mf")


def test_write_3mf_rejects_mismatched_filament_lists(tmp_path: Path):
    bad = RecipeSettings(
        filament_settings_id=["A", "B"],
        filament_colour=["#FF0000"],  # only 1 colour for 2 filaments
    )
    with pytest.raises(ValueError):
        write_3mf([_cube_mesh("X")], bad, tmp_path / "x.3mf")


# ── Recipe lookup ───────────────────────────────────────────────────────────


def test_vase_recipe_enables_spiral_and_zeros_infill():
    r = build_recipe("vase")
    assert r.spiral_mode is True
    assert r.sparse_infill_density == 0
    assert r.top_shell_layers == 0
    assert r.brim_type == "no_brim"


def test_solid_decorative_recipe_has_brim_and_gyroid_infill():
    r = build_recipe("solid_decorative")
    assert r.spiral_mode is False
    assert r.sparse_infill_density == 15
    assert r.sparse_infill_pattern == "gyroid"
    assert r.brim_type == "outer_only"
    assert r.brim_width == 5.0


def test_flat_part_recipe_uses_thinner_brim_and_more_walls():
    r = build_recipe("flat_part")
    assert r.wall_loops == 4
    assert r.sparse_infill_density == 20
    assert r.brim_width == 3.0


@pytest.mark.parametrize(
    "object_type,mode,expected_filaments",
    [
        ("solid_decorative", "none", 1),
        ("solid_decorative", "zebra", 2),
        ("solid_decorative", "quarter", 1),  # quarter = geometric split, 1 filament
        ("vase", "zebra", 2),
        ("flat_part", "none", 1),
    ],
)
def test_color_split_mode_drives_filament_count(object_type, mode, expected_filaments):
    r = build_recipe(object_type, color_split_mode=mode)
    assert len(r.filament_settings_id) == expected_filaments
    assert len(r.filament_colour) == expected_filaments


def test_filament_colours_are_red_then_yellow_for_multi_color():
    r = build_recipe("solid_decorative", color_split_mode="zebra")
    assert r.filament_colour == [COLOR_RED_HEX, COLOR_YELLOW_HEX]


@pytest.mark.parametrize(
    "token,expected_index",
    [
        ("red", 1),
        ("yellow", 2),
        ("red-q0", 1),
        ("yellow-q3", 2),
        ("", 1),
        ("unknown", 1),
    ],
)
def test_filament_index_for_color_token(token, expected_index):
    assert filament_index_for_color(token) == expected_index


# ── End-to-end happy path ───────────────────────────────────────────────────


def test_end_to_end_vase_with_two_colors_round_trips_through_writer(tmp_path: Path):
    """Build a recipe for a 2-color vase, write a .3mf with one mesh
    per filament, read it back, verify the recipe + per-object extruder
    are what we sent."""
    recipe = build_recipe("vase", color_split_mode="zebra")
    meshes = [
        _cube_mesh("Conjure_ColorA", filament_index=1),
        _cube_mesh("Conjure_ColorB", filament_index=2),
    ]
    dst = tmp_path / "vase.3mf"
    result = write_3mf(meshes, recipe, dst)

    assert result["object_count"] == 2
    assert result["filament_count"] == 2
    assert result["size"] > 0

    with zipfile.ZipFile(dst) as zf:
        ps = json.loads(zf.read("Metadata/project_settings.config"))
    assert ps["spiral_mode"] == "1"
    assert ps["filament_colour"] == [COLOR_RED_HEX, COLOR_YELLOW_HEX]
    assert ps["filament_settings_id"] == ["Bambu PLA Basic", "Bambu PLA Basic"]
