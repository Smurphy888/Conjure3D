"""
Real orchestrator for edit.apply_chain (Phase E Issue #22). Replaces
orchestrator_mock. Imports the source GLB into Blender, runs the edit chain
in the canonical auto-clean order, measures sanity, and writes
<dst_dir>/preview.glb for the frontend.

Auto-clean order (pipeline.md / HANDOFF.md, SCALE FIRST):
  scale -> voxel -> keep_largest -> recenter -> flat_bottom -> fix_normals
  -> decimate -> (vase: open_top + bridge_top_loops) -> color_split

The chain is sorted into this order before execution, so a mis-ordered
incoming chain still runs safely (voxel can never precede scale).

Every Blender failure is captured into result["errors"] — apply_chain never
raises across the JSON-RPC boundary, so the Editor always gets a structured
response it can render.
"""
import os
import sys
import time

# ── Persisted-project schema mirror (Phase H Issue #26) ──────────────────────
# The canonical schema lives in src/lib/types.ts (`ConjureProject`). The
# Python side mirrors only the version + the fields it must VALIDATE on load;
# it deliberately does not reproduce the whole TS interface. project.py
# imports these; kept here per ISSUES.md #26 ("mirrored by orchestrator.py").
PROJECT_SCHEMA_VERSION = 1
REQUIRED_PROJECT_FIELDS = (
    "version",
    "name",
    "prompt",
    "preview_task_id",
    "source_glb",
    "edits",
    "color_split_mode",
)

from blender_client import session_scope, BlenderConnectionError
from ops import (
    import_glb,
    export_glb,
    export_3mf,
    sanity as sanity_op,
    normalize,
    voxel_remesh,
    keep_largest,
    fix_normals,
    decimate,
    vase_top,
    color_split,
)

# Lower rank runs first. Unknown types sort last (and are reported).
CANONICAL_ORDER = {
    "scale_to_longest": 1,
    "voxel_remesh": 2,
    "keep_largest": 3,
    "recenter_xy": 4,
    "flat_bottom": 5,
    "fix_normals": 6,
    "decimate": 7,
    "open_top": 8,
    "bridge_top_loops": 9,
    "color_split": 10,
}

_FAILED_SANITY = {
    "manifold": False,
    "single_component": False,
    "normals_outward": False,
    "longest_dim_under_limit": False,
    "dims_mm": [0.0, 0.0, 0.0],
}


def _run_edit(edit: dict, object_type: str):
    t = edit.get("type")
    if t == "scale_to_longest":
        return normalize.scale_to_longest(float(edit["target_mm"]))
    if t == "voxel_remesh":
        return voxel_remesh.run(float(edit.get("voxel_mm", 0.8)))
    if t == "keep_largest":
        return keep_largest.run()
    if t == "recenter_xy":
        return normalize.recenter_xy()
    if t == "flat_bottom":
        return normalize.flat_bottom(float(edit.get("cut_mm", 0.8)))
    if t == "fix_normals":
        return fix_normals.run()
    if t == "decimate":
        return decimate.run(int(edit["target_faces"]))
    if t == "open_top":
        return vase_top.open_top(object_type, float(edit.get("cut_mm", 2.0)))
    if t == "bridge_top_loops":
        return vase_top.bridge_top_loops(object_type)
    if t == "color_split":
        return color_split.run(edit["mode"], int(edit.get("count", 8)))
    raise KeyError(f"unknown edit type: {t!r}")


def apply_chain(params: dict) -> dict:
    """
    params: {"src_glb": str, "edits": [Edit], "dst_dir": str}
    returns {"preview_glb", "sanity", "stl_paths", "errors"}.
    """
    src_glb = params["src_glb"]
    edits = params.get("edits") or []
    dst_dir = params.get("dst_dir") or os.path.dirname(src_glb)
    preview_glb = os.path.join(dst_dir, "preview.glb")

    object_type = (
        "vase"
        if any(e.get("type") == "open_top" for e in edits)
        else "solid_decorative"
    )
    color_split_in_chain = any(e.get("type") == "color_split" for e in edits)

    errors: list[str] = []

    # Wrap the whole chain in one persistent BlenderMCP connection. The
    # third-party addon's daemon server thread is observed to silently die
    # after the first main-thread heavy op when many short-lived connect/
    # accept cycles run against it — one connection held for the full chain
    # sidesteps that churn. Ops modules don't know about the session: their
    # execute_blender_code() calls reuse the session's socket via a thread-
    # local in blender_client.
    try:
        with session_scope():
            try:
                import_glb.run(src_glb)
            except Exception as exc:  # never cross JSON-RPC with a raise
                return {
                    "preview_glb": preview_glb,
                    "sanity": dict(_FAILED_SANITY),
                    "stl_paths": [],
                    "errors": [f"import failed: {exc}"],
                }

            ordered = sorted(edits, key=lambda e: CANONICAL_ORDER.get(e.get("type"), 99))
            for edit in ordered:
                try:
                    _run_edit(edit, object_type)
                except Exception as exc:
                    errors.append(f"{edit.get('type')}: {exc}")

            try:
                s = sanity_op.run()
                sanity = {
                    # color_split (zebra) bisects the mesh into bands; each
                    # band has open boundary edges at its cut planes BY
                    # DESIGN. The slicer prints each band with its assigned
                    # filament and the pieces tile together — boundary
                    # edges at cut planes are not a defect. Same reasoning
                    # as the single_component relaxation below: when the
                    # chain explicitly includes color_split, the post-split
                    # geometry is what the user asked for. Without this,
                    # every multi-colour print shows a misleading red
                    # manifold flag and users assume the chain failed.
                    "manifold": (
                        s["boundary_edges"] == 0 and s["non_manifold_edges"] == 0
                    ) or color_split_in_chain,
                    # color_split intentionally produces multiple components.
                    "single_component": s["components"] == 1 or color_split_in_chain,
                    "normals_outward": s["signed_volume"] > 0,
                    "longest_dim_under_limit": (
                        max(s["dims_mm"]) <= sanity_op.LONGEST_DIM_LIMIT_MM
                    ),
                    "dims_mm": s["dims_mm"],
                }
            except Exception as exc:
                errors.append(f"sanity: {exc}")
                sanity = dict(_FAILED_SANITY)

            try:
                export_glb.run(preview_glb)
            except Exception as exc:
                errors.append(f"export: {exc}")

            # Pre-bake .3mf while the session is still open. The BlenderMCP
            # addon's TCP thread dies when session_scope exits, so a fresh
            # connect at export time fails after ~7.5 s of retries. Running
            # export_3mf.run() here reuses the live socket via the thread-local
            # in blender_client. Best-effort only: failure sets threemf_path to
            # None and NEVER touches errors[] so it cannot block editApplied.
            threemf_path = None
            try:
                slug = os.path.basename(dst_dir) or "model"
                cs_edit = next(
                    (e for e in edits if e.get("type") == "color_split"), None
                )
                cs_mode = cs_edit.get("mode", "none") if cs_edit else "none"
                baked = export_3mf.run(
                    dst_dir=dst_dir,
                    slug=slug,
                    ts=time.strftime("%Y%m%d-%H%M%S"),
                    mode=cs_mode,
                    object_type=object_type,
                )
                threemf_path = baked.get("path")
            except Exception as bake_exc:
                print(
                    f"[orchestrator] pre-bake .3mf failed (non-fatal): "
                    f"{type(bake_exc).__name__}: {bake_exc}",
                    file=sys.stderr,
                    flush=True,
                )
    except BlenderConnectionError as exc:
        # session __enter__ failed — could not establish ANY connection to
        # the BlenderMCP addon's socket. Nothing was sent; report cleanly.
        return {
            "preview_glb": preview_glb,
            "sanity": dict(_FAILED_SANITY),
            "stl_paths": [],
            "errors": [f"Could not connect to Blender: {exc}"],
        }

    return {
        "preview_glb": preview_glb,
        "sanity": sanity,
        "stl_paths": [],
        "errors": errors,
        "threemf_path": threemf_path,
    }
