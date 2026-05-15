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
