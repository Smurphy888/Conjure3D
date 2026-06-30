import socket
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from ops import export_stl, import_glb, voxel_remesh, keep_largest, normalize, color_split
from blender_client import HEAVY_TIMEOUT, execute_blender_code


# ── unit tests (mocked, no Blender) ──────────────────────────────────────────

def test_rejects_unknown_mode():
    with pytest.raises(ValueError, match="mode must be one of"):
        export_stl.run("d", "slug", "20260516-105400", "rainbow")


def test_rejects_non_str_args():
    with pytest.raises(TypeError):
        export_stl.run(123, "slug", "ts", "none")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        export_stl.run("d", None, "ts", "none")  # type: ignore[arg-type]


def test_color_token_canonical_map():
    # none mode never adds a suffix, whatever the object is called.
    assert export_stl.color_token("Scene", "none") == ""
    assert export_stl.color_token("anything", "none") == ""
    # bisect halves always get distinct suffixes, even in "none" mode.
    assert export_stl.color_token("Conjure_HalfA", "none") == "a"
    assert export_stl.color_token("Conjure_HalfB", "none") == "b"
    # zebra groups.
    assert export_stl.color_token("Conjure_ColorA", "zebra") == "red"
    assert export_stl.color_token("Conjure_ColorB", "zebra") == "yellow"
    # quarter wedges: Conjure_Q{i} → "q{i}" (no colour prefix; all same filament).
    assert export_stl.color_token("Conjure_Q0", "quarter") == "q0"
    assert export_stl.color_token("Conjure_Q1", "quarter") == "q1"
    assert export_stl.color_token("Conjure_Q3", "quarter") == "q3"
    # old two-index names no longer match (regression guard).
    assert export_stl.color_token("Conjure_Q0_0", "quarter") == ""
    # unrecognised name under a split mode falls back to bare stem.
    assert export_stl.color_token("Cube", "zebra") == ""


def test_none_mode_code_pins_binary_mm_axes_and_returns_stats():
    captured = {}

    def fake(code, timeout=None, **kw):
        captured["code"] = code
        captured["timeout"] = timeout
        return ('{"mode": "none", "dir": "d", "count": 1, '
                '"files": [{"path": "d/vase_20260516-105400.stl", '
                '"color": "", "size": 84}]}')

    with patch("ops.export_stl.execute_blender_code", side_effect=fake):
        out = export_stl.run("d", "vase", "20260516-105400", "none")

    code = captured["code"]
    # The whole point of the mocked test: pin the exporter kwargs so a
    # future fire that "fixes" a param name trips immediately.
    assert "bpy.ops.wm.stl_export(" in code
    assert "ascii_format=False" in code
    assert "global_scale=1000.0" in code
    assert "export_selected_objects=True" in code
    assert "apply_modifiers=True" in code
    assert "forward_axis='Y'" in code
    assert "up_axis='Z'" in code
    # Must NOT use the legacy export_mesh.stl kwarg names.
    assert "use_mesh_modifiers" not in code
    assert "use_selection" not in code
    assert "export_mesh.stl" not in code
    # Embedded color_token must still carry the canonical patterns.
    assert "Conjure_ColorA" in code and "Conjure_ColorB" in code
    assert r"Conjure_Q(\d+)$" in code
    assert captured["timeout"] == HEAVY_TIMEOUT
    assert out["count"] == 1 and out["mode"] == "none"


def test_stem_is_slugified_windows_legal_and_code_compiles():
    captured = {}

    def fake(code, timeout=None, **kw):
        captured["code"] = code
        return '{"mode": "none", "dir": "d", "count": 1, "files": [1]}'

    # Apostrophe in name + colons in a raw timestamp must not survive into
    # the on-disk stem nor break the generated snippet.
    with patch("ops.export_stl.execute_blender_code", side_effect=fake):
        export_stl.run("d", "Mom's Vase!", "2026-05-16 10:54:00", "none")

    code = captured["code"]
    # slugify strips ':' entirely and turns the space into '-', so the
    # HHMMSS digits run together — deterministic and Windows-legal.
    assert 'STEM = "moms-vase_2026-05-16-105400"' in code
    assert ":" not in code.split("STEM = ")[1].splitlines()[0]
    compile(code, "<generated>", "exec")  # snippet is valid Python


def test_bisect_two_files_a_b():
    """Bisect produces 2 STL files (_a / _b) even though mode is 'none'.
    The count validator must not raise because it detects bisect halves."""
    def fake(code, timeout=None, **kw):
        return ('{"mode": "none", "dir": "d", "count": 2, "files": ['
                '{"path": "d/v_ts_a.stl", "color": "a", "size": 80},'
                '{"path": "d/v_ts_b.stl", "color": "b", "size": 80}]}')

    with patch("ops.export_stl.execute_blender_code", side_effect=fake):
        out = export_stl.run("d", "v", "ts", "none")
    assert out["count"] == 2
    assert {f["color"] for f in out["files"]} == {"a", "b"}


def test_zebra_two_files_red_yellow():
    def fake(code, timeout=None, **kw):
        return ('{"mode": "zebra", "dir": "d", "count": 2, "files": ['
                '{"path": "d/v_ts_red.stl", "color": "red", "size": 90},'
                '{"path": "d/v_ts_yellow.stl", "color": "yellow", "size": 90}]}')

    with patch("ops.export_stl.execute_blender_code", side_effect=fake):
        out = export_stl.run("d", "v", "ts", "zebra")
    assert out["count"] == 2
    assert {f["color"] for f in out["files"]} == {"red", "yellow"}


def test_quarter_four_files():
    """Quarter produces 4 STL files (q0–q3), one per wedge, same colour."""
    files = [{"path": f"d/v_ts_q{q}.stl", "color": f"q{q}", "size": 80}
             for q in range(4)]
    payload = {"mode": "quarter", "dir": "d", "count": 4, "files": files}
    import json as _j
    with patch("ops.export_stl.execute_blender_code",
               return_value=_j.dumps(payload)):
        out = export_stl.run("d", "v", "ts", "quarter")
    assert out["count"] == 4 and len(out["files"]) == 4
    assert {f["color"] for f in out["files"]} == {"q0", "q1", "q2", "q3"}


def test_count_mismatch_raises_legibly():
    with patch("ops.export_stl.execute_blender_code",
               return_value='{"mode": "quarter", "count": 3, "files": []}'):
        with pytest.raises(RuntimeError, match="expected 4 STL file.*got 3"):
            export_stl.run("d", "v", "ts", "quarter")


def test_no_json_line_raises():
    with patch("ops.export_stl.execute_blender_code", return_value="boom\n"):
        with pytest.raises(RuntimeError, match="No JSON stats line"):
            export_stl.run("d", "v", "ts", "none")


# ── live integration tests (skipped when Blender not running) ────────────────

def _port_open(host="127.0.0.1", port=9876, timeout=0.5):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


_LIVE_REASON = "Blender + BlenderMCP not running on :9876"

FIXTURE_DIR = Path(__file__).parent / "fixtures"
VASE_GLB = str(FIXTURE_DIR / "sample_vase.glb")


def _prep_vase():
    import_glb.run(VASE_GLB)
    normalize.scale_to_longest(80.0)
    voxel_remesh.run(voxel_size_mm=0.8)
    keep_largest.run()


def _assert_binary_nonempty(path: str):
    p = Path(path)
    assert p.is_file(), f"missing STL: {path}"
    data = p.read_bytes()
    assert len(data) > 0, f"empty STL: {path}"
    assert data[:5].lower() != b"solid", f"STL is ASCII not binary: {path}"


@pytest.mark.skipif(not _port_open(), reason=_LIVE_REASON)
def test_live_none_writes_one_binary_stl(tmp_path):
    _prep_vase()
    out = export_stl.run(str(tmp_path), "vase", "20260516-105400", "none")
    assert out["count"] == 1
    f = out["files"][0]
    assert f["color"] == ""
    assert Path(f["path"]).name == "vase_20260516-105400.stl"
    _assert_binary_nonempty(f["path"])


@pytest.mark.skipif(not _port_open(), reason=_LIVE_REASON)
def test_live_zebra_writes_two_binary_stls(tmp_path):
    _prep_vase()
    color_split.run("zebra", count=8)
    out = export_stl.run(str(tmp_path), "vase", "20260516-105400", "zebra")
    assert out["count"] == 2
    assert {f["color"] for f in out["files"]} == {"red", "yellow"}
    for f in out["files"]:
        _assert_binary_nonempty(f["path"])


@pytest.mark.skipif(not _port_open(), reason=_LIVE_REASON)
def test_live_quarter_writes_four_binary_stls(tmp_path):
    _prep_vase()
    color_split.run("quarter")
    out = export_stl.run(str(tmp_path), "vase", "20260516-105400", "quarter")
    assert out["count"] == 4
    assert {f["color"] for f in out["files"]} == {f"q{q}" for q in range(4)}
    for f in out["files"]:
        _assert_binary_nonempty(f["path"])
