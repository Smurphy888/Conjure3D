import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import orchestrator


GOOD_SANITY = {
    "boundary_edges": 0,
    "non_manifold_edges": 0,
    "object_count": 1,
    "components": 1,
    "signed_volume": 12.5,
    "dims_mm": [80.0, 30.0, 30.0],
}

# A typical vase chain, deliberately scrambled to prove canonical reordering.
SCRAMBLED_EDITS = [
    {"type": "voxel_remesh", "voxel_mm": 0.8},
    {"type": "scale_to_longest", "target_mm": 80},
    {"type": "decimate", "target_faces": 50000},
    {"type": "keep_largest"},
    {"type": "recenter_xy"},
    {"type": "flat_bottom", "cut_mm": 1},
    {"type": "fix_normals"},
    {"type": "open_top", "cut_mm": 2},
    {"type": "bridge_top_loops"},
    {"type": "color_split", "mode": "zebra", "count": 8},
]


def _patched(calls):
    """Patch every op the orchestrator dispatches to, recording call order."""
    def rec(name, ret=None):
        def fn(*a, **k):
            calls.append((name, a, k))
            return ret if ret is not None else {}
        return fn

    return [
        patch.object(orchestrator.import_glb, "run", side_effect=rec("import")),
        patch.object(orchestrator.export_glb, "run", side_effect=rec("export")),
        patch.object(orchestrator.sanity_op, "run",
                     side_effect=rec("sanity", dict(GOOD_SANITY))),
        patch.object(orchestrator.normalize, "scale_to_longest",
                     side_effect=rec("scale_to_longest")),
        patch.object(orchestrator.normalize, "recenter_xy",
                     side_effect=rec("recenter_xy")),
        patch.object(orchestrator.normalize, "flat_bottom",
                     side_effect=rec("flat_bottom")),
        patch.object(orchestrator.voxel_remesh, "run",
                     side_effect=rec("voxel_remesh")),
        patch.object(orchestrator.keep_largest, "run",
                     side_effect=rec("keep_largest")),
        patch.object(orchestrator.fix_normals, "run",
                     side_effect=rec("fix_normals")),
        patch.object(orchestrator.decimate, "run", side_effect=rec("decimate")),
        patch.object(orchestrator.vase_top, "open_top",
                     side_effect=rec("open_top")),
        patch.object(orchestrator.vase_top, "bridge_top_loops",
                     side_effect=rec("bridge_top_loops")),
        patch.object(orchestrator.color_split, "run",
                     side_effect=rec("color_split")),
    ]


def _run(params):
    calls = []
    ctxs = _patched(calls)
    for c in ctxs:
        c.start()
    try:
        result = orchestrator.apply_chain(params)
    finally:
        for c in ctxs:
            c.stop()
    return result, calls


def test_chain_runs_in_canonical_order_import_first_export_last():
    result, calls = _run({
        "src_glb": "/proj/src.glb",
        "edits": SCRAMBLED_EDITS,
        "dst_dir": "/proj",
    })
    names = [c[0] for c in calls]
    assert names[0] == "import"
    assert names[-1] == "export"
    # The op sequence between import and sanity, in canonical order.
    op_seq = [n for n in names if n not in ("import", "export", "sanity")]
    assert op_seq == [
        "scale_to_longest", "voxel_remesh", "keep_largest", "recenter_xy",
        "flat_bottom", "fix_normals", "decimate", "open_top",
        "bridge_top_loops", "color_split",
    ]
    # sanity is measured after the chain, before export
    assert names.index("sanity") < names.index("export")
    assert result["errors"] == []


def test_import_called_with_src_and_export_with_preview_path():
    _, calls = _run({
        "src_glb": "/proj/src.glb",
        "edits": [{"type": "fix_normals"}],
        "dst_dir": "/proj",
    })
    import_call = next(c for c in calls if c[0] == "import")
    export_call = next(c for c in calls if c[0] == "export")
    assert import_call[1][0] == "/proj/src.glb"
    assert export_call[1][0].replace("\\", "/") == "/proj/preview.glb"


def test_dst_dir_falls_back_to_src_directory_when_empty():
    result, _ = _run({
        "src_glb": "/some/where/model.glb",
        "edits": [],
        "dst_dir": "",
    })
    assert result["preview_glb"].replace("\\", "/") == "/some/where/preview.glb"


def test_sanity_shape_matches_frontend_interface():
    result, _ = _run({"src_glb": "/p/s.glb", "edits": [], "dst_dir": "/p"})
    s = result["sanity"]
    assert set(s) == {
        "manifold", "single_component", "normals_outward",
        "longest_dim_under_limit", "dims_mm",
    }
    assert s["manifold"] is True
    assert s["single_component"] is True
    assert s["normals_outward"] is True
    assert s["longest_dim_under_limit"] is True
    assert s["dims_mm"] == [80.0, 30.0, 30.0]
    assert result["stl_paths"] == []


def test_object_type_inferred_vase_when_open_top_present():
    _, calls = _run({
        "src_glb": "/p/s.glb",
        "edits": [{"type": "open_top", "cut_mm": 2}, {"type": "bridge_top_loops"}],
        "dst_dir": "/p",
    })
    open_call = next(c for c in calls if c[0] == "open_top")
    assert open_call[1][0] == "vase"  # object_type positional arg


def test_color_split_chain_marks_single_component_true_despite_multi():
    # sanity reports 8 components (quarter) but color_split was in the chain
    multi = dict(GOOD_SANITY)
    multi["components"] = 8
    calls = []
    ctxs = _patched(calls)
    for c in ctxs:
        c.start()
    orchestrator.sanity_op.run.side_effect = lambda *a, **k: dict(multi)
    try:
        result = orchestrator.apply_chain({
            "src_glb": "/p/s.glb",
            "edits": [{"type": "color_split", "mode": "quarter"}],
            "dst_dir": "/p",
        })
    finally:
        for c in ctxs:
            c.stop()
    assert result["sanity"]["single_component"] is True


def test_unknown_edit_recorded_in_errors_not_raised():
    result, _ = _run({
        "src_glb": "/p/s.glb",
        "edits": [{"type": "frobnicate"}],
        "dst_dir": "/p",
    })
    assert any("frobnicate" in e for e in result["errors"])
    # chain still completes and returns a structured result
    assert "preview_glb" in result


def test_import_failure_returns_structured_error_not_raise():
    with patch.object(orchestrator.import_glb, "run",
                       side_effect=RuntimeError("boom")):
        result = orchestrator.apply_chain({
            "src_glb": "/p/s.glb", "edits": [], "dst_dir": "/p",
        })
    assert result["errors"] == ["import failed: boom"]
    assert result["sanity"]["manifold"] is False
    assert result["preview_glb"].replace("\\", "/") == "/p/preview.glb"


def test_op_failure_is_collected_and_chain_continues():
    calls = []
    ctxs = _patched(calls)
    for c in ctxs:
        c.start()
    orchestrator.decimate.run.side_effect = RuntimeError("decimate exploded")
    try:
        result = orchestrator.apply_chain({
            "src_glb": "/p/s.glb",
            "edits": [{"type": "decimate", "target_faces": 50000},
                      {"type": "fix_normals"}],
            "dst_dir": "/p",
        })
    finally:
        for c in ctxs:
            c.stop()
    assert any("decimate exploded" in e for e in result["errors"])
    # fix_normals still ran after the failing decimate
    assert any(c[0] == "fix_normals" for c in calls)
