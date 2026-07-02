import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import project
import main
from orchestrator import PROJECT_SCHEMA_VERSION


def _project_dict(name="Mom's Vase"):
    return {
        "name": name,
        "prompt": "a stylized vase",
        "preview_task_id": "task-123",
        "source_glb": "C:/tmp/src.glb",
        "edits": [{"type": "scale_to_longest", "target_mm": 80}],
        "color_split_mode": "zebra",
        "last_sanity": None,
    }


def _make_artifacts(tmp_path):
    glb = tmp_path / "preview.glb"
    glb.write_bytes(b"GLB-BYTES")
    s1 = tmp_path / "v_red.stl"
    s1.write_bytes(b"RED")
    s2 = tmp_path / "v_yellow.stl"
    s2.write_bytes(b"YELLOW")
    return str(glb), [str(s1), str(s2)]


def test_error_codes_frozen_contract():
    assert project.ERROR_CODES == (
        "SCHEMA_VERSION_MISMATCH",
        "PROJECT_FILE_INVALID",
        "ARTIFACT_MISSING",
    )


def test_save_writes_versioned_json_and_copies_artifacts(tmp_path):
    glb, stls = _make_artifacts(tmp_path)
    out = tmp_path / "out"
    r = project.save({
        "dst_dir": str(out),
        "project": _project_dict(),
        "artifacts": {"preview_glb": glb, "stl_paths": stls},
    })
    assert r["ok"] is True
    pf = Path(r["project_file"])
    assert pf.name == "moms-vase.conjure3d.json"
    doc = json.loads(pf.read_text(encoding="utf-8"))
    assert doc["version"] == PROJECT_SCHEMA_VERSION == 1
    assert doc["color_split_mode"] == "zebra"
    art_dir = Path(r["artifact_dir"])
    assert art_dir.name == "moms-vase.conjure3d"
    # Byte-identical record = the COPIES in the sibling folder.
    assert (art_dir / "preview.glb").read_bytes() == b"GLB-BYTES"
    assert (art_dir / "v_red.stl").read_bytes() == b"RED"
    assert doc["artifacts"]["preview_glb"] == "preview.glb"
    assert doc["artifacts"]["stl_paths"] == ["v_red.stl", "v_yellow.stl"]


def test_save_empty_stl_list_is_valid_pre_export(tmp_path):
    glb, _ = _make_artifacts(tmp_path)
    r = project.save({
        "dst_dir": str(tmp_path / "o"),
        "project": _project_dict(),
        "artifacts": {"preview_glb": glb, "stl_paths": []},
    })
    assert r["ok"] is True
    doc = json.loads(Path(r["project_file"]).read_text(encoding="utf-8"))
    assert doc["artifacts"]["stl_paths"] == []
    assert doc["artifacts"]["preview_glb"] == "preview.glb"


def test_save_rejects_missing_required_field(tmp_path):
    bad = _project_dict()
    del bad["source_glb"]
    r = project.save({
        "dst_dir": str(tmp_path),
        "project": bad,
        "artifacts": {},
    })
    assert r["error_code"] == "PROJECT_FILE_INVALID"
    assert "source_glb" in r["missing"]


def test_save_then_load_round_trips(tmp_path):
    glb, stls = _make_artifacts(tmp_path)
    saved = project.save({
        "dst_dir": str(tmp_path / "p"),
        "project": _project_dict(),
        "artifacts": {"preview_glb": glb, "stl_paths": stls},
    })
    loaded = project.load({"project_file": saved["project_file"]})
    assert loaded["ok"] is True
    assert loaded["project"]["name"] == "Mom's Vase"
    assert loaded["project"]["edits"] == [
        {"type": "scale_to_longest", "target_mm": 80}
    ]
    assert loaded["project"]["color_split_mode"] == "zebra"
    # Resolved artifact paths point into the sibling folder and exist.
    assert Path(loaded["artifacts"]["preview_glb"]).read_bytes() == b"GLB-BYTES"
    assert [Path(p).read_bytes() for p in loaded["artifacts"]["stl_paths"]] == [
        b"RED", b"YELLOW"
    ]
    assert "warning_code" not in loaded


def test_load_version_mismatch(tmp_path):
    pf = tmp_path / "x.conjure3d.json"
    doc = {"version": 99, "name": "x", "prompt": "", "preview_task_id": None,
           "source_glb": "s", "edits": [], "color_split_mode": "none"}
    pf.write_text(json.dumps(doc), encoding="utf-8")
    r = project.load({"project_file": str(pf)})
    assert r["error_code"] == "SCHEMA_VERSION_MISMATCH"
    assert r["file_version"] == 99


def test_load_invalid_json(tmp_path):
    pf = tmp_path / "broken.conjure3d.json"
    pf.write_text("{ not json", encoding="utf-8")
    r = project.load({"project_file": str(pf)})
    assert r["error_code"] == "PROJECT_FILE_INVALID"


def test_load_missing_required_field(tmp_path):
    pf = tmp_path / "y.conjure3d.json"
    pf.write_text(json.dumps({"version": 1, "name": "y"}), encoding="utf-8")
    r = project.load({"project_file": str(pf)})
    assert r["error_code"] == "PROJECT_FILE_INVALID"
    assert "prompt" in r["missing"]


def test_load_warns_but_succeeds_when_artifacts_moved(tmp_path):
    glb, stls = _make_artifacts(tmp_path)
    saved = project.save({
        "dst_dir": str(tmp_path / "q"),
        "project": _project_dict(),
        "artifacts": {"preview_glb": glb, "stl_paths": stls},
    })
    # Simulate the sibling folder being moved/deleted after save.
    art_dir = Path(saved["artifact_dir"])
    for f in art_dir.iterdir():
        f.unlink()
    r = project.load({"project_file": saved["project_file"]})
    assert r["ok"] is True  # non-fatal
    assert r["warning_code"] == "ARTIFACT_MISSING"
    assert len(r["missing_artifacts"]) == 3


def test_save_and_load_reject_bad_param_types():
    with pytest.raises(TypeError):
        project.save({"dst_dir": "", "project": {}})
    with pytest.raises(TypeError):
        project.load({"project_file": 123})  # type: ignore[arg-type]


# ── loaded-chain re-validation signal (S5) ─────────────────────────────────────

def test_load_flags_valid_edit_chain(tmp_path):
    glb, stls = _make_artifacts(tmp_path)
    saved = project.save({
        "dst_dir": str(tmp_path / "v"),
        "project": _project_dict(),
        "artifacts": {"preview_glb": glb, "stl_paths": stls},
    })
    r = project.load({"project_file": saved["project_file"]})
    assert r["ok"] is True
    assert r["edits_valid"] is True
    assert r["edits_validation_error"] is None


def test_load_flags_out_of_range_edit_chain_without_failing(tmp_path):
    """A tampered/corrupt chain (target_mm above the schema's le=300 cap) still
    loads — the orchestrator is already injection-safe — but is flagged so the
    UI can warn before re-running."""
    pf = tmp_path / "bad.conjure3d.json"
    doc = {
        "version": 1, "name": "Bad", "prompt": "p", "preview_task_id": None,
        "source_glb": "s.glb", "color_split_mode": "none",
        "edits": [{"type": "scale_to_longest", "target_mm": 99999}],
    }
    pf.write_text(json.dumps(doc), encoding="utf-8")
    r = project.load({"project_file": str(pf)})
    assert r["ok"] is True              # non-fatal
    assert r["edits_valid"] is False
    assert r["edits_validation_error"]  # non-empty message
    # The raw edits are still returned verbatim (the UI decides what to do).
    assert r["project"]["edits"] == [{"type": "scale_to_longest", "target_mm": 99999}]


def test_load_flags_unknown_edit_type(tmp_path):
    pf = tmp_path / "unknown.conjure3d.json"
    doc = {
        "version": 1, "name": "U", "prompt": "p", "preview_task_id": None,
        "source_glb": "s.glb", "color_split_mode": "none",
        "edits": [{"type": "frobnicate", "wat": 1}],
    }
    pf.write_text(json.dumps(doc), encoding="utf-8")
    r = project.load({"project_file": str(pf)})
    assert r["ok"] is True
    assert r["edits_valid"] is False


def test_dispatch_project_save_load_over_rpc(tmp_path):
    glb = tmp_path / "preview.glb"
    glb.write_bytes(b"G")
    save_req = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "project.save",
        "params": {
            "dst_dir": str(tmp_path / "rpc"),
            "project": _project_dict("RpcProj"),
            "artifacts": {"preview_glb": str(glb), "stl_paths": []},
        },
    })
    out = io.StringIO()
    main.run_loop(io.StringIO(save_req + "\n"), out)
    saved = json.loads(out.getvalue())["result"]
    assert saved["ok"] is True

    load_req = json.dumps({
        "jsonrpc": "2.0", "id": 2, "method": "project.load",
        "params": {"project_file": saved["project_file"]},
    })
    out2 = io.StringIO()
    main.run_loop(io.StringIO(load_req + "\n"), out2)
    loaded = json.loads(out2.getvalue())["result"]
    assert loaded["ok"] is True
    assert loaded["project"]["name"] == "RpcProj"
