# Manual Blender Tests (Phase E live acceptance)

Phase E issues are committed on **mocked unit-test acceptance** because Blender
does not stay running between unattended scheduled fires. The live integration
tests below must be run by the user in a session with Blender 4.2+ open and the
BlenderMCP addon connected (`netstat -an | findstr 9876` showing
`0.0.0.0:9876 LISTENING`). Phase E is not considered fully done until every
section here is green.

To run a section: open Blender + BlenderMCP, then from the repo root run the
listed command. The `skipif(not _port_open())` guards auto-enable the live
tests once port 9876 is reachable.

---

## Issue #16 — voxel_remesh + keep_largest + import_glb

Command: `pytest sidecar/tests/test_ops_voxel_keep_largest.py -k live`

Live tests:
- `test_live_voxel_remesh_keep_largest_vase_yields_one_component_zero_boundary`
- `test_live_voxel_remesh_guitar_under_200k_faces_after_scale`
- `test_live_keep_largest_collapses_multi_component_input_to_one`

Acceptance:
- Output mesh on `sample_vase.glb`: 1 component, 0 boundary edges
- Voxel remesh on `sample_guitar.glb` (after scale step) produces < 200k faces
  (proves scale-first ordering)
- `keep_largest` collapses a multi-component input down to a single component

Status: PENDING USER VERIFICATION

---

## Issue #17 — scale_to_longest + recenter_xy + flat_bottom

Command: `pytest sidecar/tests/test_ops_normalize.py -k live`

Live tests:
- `test_live_scale_to_longest_hits_target_within_tolerance`
- `test_live_recenter_xy_centers_bbox_and_grounds_base`
- `test_live_flat_bottom_full_pipeline_leaves_base_on_z0`

Acceptance:
- After `scale_to_longest(80)` on `sample_vase.glb`: longest dim = 80 mm ± 0.1 mm
- After `recenter_xy`: bbox centered at X=0, Y=0 and base min-Z = 0, all
  within ± 0.001 mm
- After full Phase-6 prefix (scale → voxel → keep_largest → recenter →
  flat_bottom) on the vase: base min-Z = 0 ± 0.001 mm and mesh not collapsed

Known risk if a measurement assertion fails: `obj.bound_box` can read stale
immediately after EDIT-mode ops / transform_apply on some Blender 4.x builds.
Fix is to insert `bpy.context.view_layer.update()` before each `bound_box`
read in `ops/normalize.py` (recenter_xy and flat_bottom).

Status: PENDING USER VERIFICATION

---

## Issue #18 — fix_normals (signed-volume check + flip)

Command: `pytest sidecar/tests/test_ops_fix_normals.py -k live`

Live tests:
- `test_live_fix_normals_makes_volume_positive_for_vase`
- `test_live_fix_normals_repairs_inside_out_cube`

Acceptance:
- After `fix_normals` on `sample_vase.glb`: signed volume > 0
- An explicitly inverted cube: `volume_before` < 0, `flipped` is True,
  `volume_after` > 0 (signed volume positive after this op for any input)

Status: PENDING USER VERIFICATION
