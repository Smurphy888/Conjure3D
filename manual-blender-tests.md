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

---

## Issue #19 — decimate (COLLAPSE modifier to target face count)

Command: `pytest sidecar/tests/test_ops_decimate.py -k live`

Live tests:
- `test_live_decimate_voxel_remeshed_vase_hits_target`
- `test_live_decimate_skips_small_mesh`

Acceptance:
- Full Phase-6 prefix on the vase (scale → voxel → keep_largest →
  decimate(50000)): `faces_after` <= 50000, `faces_after` < `faces_before`,
  and the applied `ratio` < 0.1 (voxel-remeshed inputs overproduce)
- A mesh already under target (default cube): `ratio` == 1.0, face count
  unchanged

Status: PENDING USER VERIFICATION

---

## Issue #20 — open_top + bridge_top_loops (vase-only)

Command: `pytest sidecar/tests/test_ops_vase_top.py -k live`

Live tests:
- `test_live_open_top_then_bridge_yields_watertight_vase`
- `test_live_solid_decorative_skips_both_ops_unchanged`

Acceptance:
- `object_type == "vase"`: after `open_top` boundary_edges > 0 (mouth open),
  then `bridge_top_loops` returns watertight (boundary_edges == 0)
- `object_type == "solid_decorative"`: both ops return `skipped: True`
  without contacting Blender (mesh unchanged)

Status: PENDING USER VERIFICATION

---

## Issue #21 — color_split (zebra + quarter)

Command: `pytest sidecar/tests/test_ops_color_split.py -k live`

Live tests:
- `test_live_zebra_8_yields_two_meshes_volume_preserved`
- `test_live_quarter_yields_eight_meshes_volume_preserved`

Acceptance:
- `zebra` count=8 on the prepped vase: exactly 2 output meshes, total
  abs-volume within 1% of input
- `quarter` on the prepped vase: 8 output meshes (4 wedges x 2 colors),
  total abs-volume within 1% of input
- (ISSUES.md #21 acceptance 3 — Editor warning when object_type != vase —
  is ALREADY satisfied by src/lib/edits.ts `shouldWarnColorSplit`, 17
  passing vitest cases; this op is backend-only.)

QUARTER SPEC NOTE: implemented as 4 angular wedges x 2 alternating colors =
8 outputs (pipeline.md "4 wedge sets per color" + ISSUES.md "8 outputs").
If the user intended a different count, reconcile here — cheap to change.

Manifold-per-output is asserted indirectly (volume preservation within 1%);
add explicit per-mesh manifold checks during live verification if desired.

Status: PENDING USER VERIFICATION

## Issue #22 — Wire real `edit.apply_chain` end-to-end (Phase E capstone)

Backend wiring is committed on mocked acceptance: `orchestrator.apply_chain`
replaces `orchestrator_mock`, dispatches the real ops in canonical auto-clean
order (scale → voxel → keep_largest → recenter → flat_bottom → fix_normals →
decimate → vase open_top/bridge → color_split), measures real sanity via
`ops/sanity.py`, and writes `<dst_dir>/preview.glb` via `ops/export_glb.py`.
9/9 mocked orchestrator tests pass (`tests/test_orchestrator.py`); full
sidecar suite 150 passed, 15 skipped (live-gated).

ISSUES.md #22 acceptance is inherently live-only and is the Phase E closing
gate. Verify with Blender 4.2+ open and BlenderMCP connected:

1. Frontend end-to-end, sample_vase.glb:
   Command: pnpm tauri dev → New Project → load sidecar/tests/fixtures/sample_vase.glb
            → Editor → apply a vase chain (scale_to_longest 180, voxel_remesh,
            keep_largest, recenter_xy, flat_bottom, fix_normals, decimate 50000,
            open_top, bridge_top_loops)
   Acceptance: preview.glb written to the project dir and renders in the
   Editor; sanity panel shows manifold=true, single_component=true,
   normals_outward=true, longest_dim_under_limit=true; errors=[].

2. Frontend end-to-end, sample_guitar.glb (solid_decorative, no vase ops):
   Command: same flow, load sidecar/tests/fixtures/sample_guitar.glb, apply
            scale_to_longest 240 + voxel_remesh + keep_largest + recenter_xy
            + flat_bottom + fix_normals + decimate 50000
   Acceptance: real preview.glb renders; sanity all-true; errors=[].

3. Round-trip timing:
   Command: time one apply_chain run on a ~50k-poly mesh (post-decimate)
   Acceptance: apply round-trip < 8 s on a typical dev machine.

Status: PENDING USER VERIFICATION

## Phase F Issue #23 — real Meshy API (live acceptance)

Command/flow:
1. Edit sidecar/main.py: change `import meshy_mock as _meshy` -> `import meshy as _meshy`
2. Meshy API key is already in Windows Credential Manager (service conjure3d).
3. `pnpm tauri dev` -> New Project -> enter a prompt -> Generate
4. Confirm a real GLB downloads and renders in the editor preview.
5. Network-kill check: block assets.meshy.ai in hosts, retry -> error shown
   verbatim, NO auto-retry (credits not double-spent).
6. Revert main.py import back to meshy_mock if you want subsequent autonomous
   fires to stay mock-only (recommended until release).

Acceptance:
- Real prompt -> real Meshy task id -> real GLB on disk, size > 0, glTF magic
- Error path surfaces Meshy's message verbatim, no silent retry
- Task ids recorded in the project's .conjure3d.json

Status: PENDING USER VERIFICATION

## Phase H Issue #26 — `<slug>.conjure3d.json` save/load

Backend + schema committed on mocked acceptance. `sidecar/project.py`
`save`/`load` (RPCs `project.save`/`project.load`); schema version +
required fields mirrored in `orchestrator.py`
(`PROJECT_SCHEMA_VERSION = 1`, `REQUIRED_PROJECT_FIELDS`); canonical TS
schema `ConjureProject` in `src/lib/types.ts`; pure
`serializeProject`/`deserializeProject` in `src/lib/project.ts`. Tests:
sidecar 11/11 (`tests/test_project.py`), vitest 10/10
(`src/lib/project.test.ts`); full sidecar 193 passed/18 skipped, vitest
47 passed, `tsc --noEmit` clean.

BYTE-IDENTICAL DESIGN (verify the intent holds, do not "fix" it): the
byte-identical guarantee comes from `save` *copying* preview.glb + STLs
into the sibling `<slug>.conjure3d/` folder — those copies are the
record. `load` restores Editor state from JSON and points at the copies.
Re-running `edit.apply_chain` is a separate editability affordance, NOT
the byte-identical mechanism (Blender export is not bit-deterministic).

ISSUES.md #26 acceptance is UI/live. Verify with the app running:

1. Save → close app → reopen → Open project file: the restored Editor
   state matches (name, prompt, edits, color-split mode) and the
   preview GLB + STLs in the sibling folder are byte-identical to
   pre-close (compare with `Get-FileHash`).
2. Version guard: hand-edit a saved `.conjure3d.json` to `version: 2`,
   Open it → frontend shows the `SCHEMA_VERSION_MISMATCH` message, does
   not crash, does not load partial state.
3. Moved-artifacts warning: move the sibling folder, Open → load still
   succeeds with an `ARTIFACT_MISSING` warning surfaced (non-fatal).

Frontend Editor Save/Open buttons + Tauri file-dialog wiring is
DEFERRED (UI surface area, separate review pass). The pure serializer +
sidecar IO + RPC contract this acceptance depends on are complete and
tested; only the Editor button wiring + dialog plumbing remains.

Status: PENDING USER VERIFICATION

## Phase G Issue #25 — `slicer.launch` for Bambu Studio

Backend committed on mocked acceptance: `sidecar/slicer.py` reads
`bambu_path` from settings only (strict per ISSUES.md #25 — no auto-detect
fallback here), validates the exe + every STL exists, then spawns Bambu
detached (`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`) with an argv list.
RPC `slicer.launch` registered in `main.py`. 9/9 mocked tests pass
(`tests/test_slicer.py`); full sidecar suite 182 passed, 18 skipped.

ISSUES.md #25 acceptance is inherently live + UI. Verify with the app
running:

1. Happy path — `pnpm tauri dev` → run a project through Editor → Export.
   With `bambu_path` set in Settings and STLs written by Issue #24's
   `export_stl`, hitting Export opens Bambu Studio with all STL files
   loaded. Close/restart the app afterward and confirm Bambu stays open
   (detached spawn).
2. Missing-path path — clear `bambu_path` in `%LOCALAPPDATA%\Conjure3D\
   settings.json` (or via Settings UI), hit Export. Expect the
   `BAMBU_PATH_MISSING` error code → frontend opens the Settings dialog →
   user browses to `bambu-studio.exe` → retry Export → Bambu opens.

Error-code contract the frontend must branch on (frozen, pinned in tests):
`BAMBU_PATH_MISSING`, `BAMBU_PATH_INVALID`, `NO_STL_FILES`,
`STL_FILES_MISSING`.

Frontend Export-screen wiring is DEFERRED — `src/screens/Export.tsx` is
still a stub and depends on `stl_paths` plumbing that does not exist yet
(`orchestrator.apply_chain` still returns `stl_paths: []`; see the #24/#25
decision punt below). Wiring Export.tsx + the Settings-browse-retry loop is
the remaining work for this acceptance to go green.

Status: PENDING USER VERIFICATION

## Phase G Issue #24 — `export_stl` per-color binary STLs

Committed on mocked acceptance (Blender does not stay up between unattended
fires; same precedent as Phase E). `ops/export_stl.py` writes one binary STL
per mesh object via Blender 4.2+ `bpy.ops.wm.stl_export`
(`ascii_format=False`, `global_scale=1000.0`, `export_selected_objects=True`,
`forward_axis='Y'`, `up_axis='Z'`). Mocked suite pins every exporter kwarg so
a wrong param name trips immediately; live run below is the only thing that
exercises the real Blender exporter.

Command: `pytest sidecar/tests/test_ops_export_stl.py -k live`

Live tests:
- `test_live_none_writes_one_binary_stl`
- `test_live_zebra_writes_two_binary_stls`
- `test_live_quarter_writes_eight_binary_stls`

Acceptance:
- none mode on the prepped vase → exactly 1 file `vase_<ts>.stl`
- zebra (count=8) → exactly 2 files `..._red.stl`, `..._yellow.stl`
- quarter → exactly 8 files `..._red-q0.stl` … `..._yellow-q3.stl`
- Every file: size > 0 and first 5 bytes ≠ `solid` (binary, not ASCII)
- ORIENTATION (visual, not asserted): open one STL in Bambu Studio and
  confirm it is upright and mm-scaled, not rotated. `forward_axis='Y'`/
  `up_axis='Z'` are pinned to the legacy convention; if a 4.2.x point
  release loads it sideways, adjust those two kwargs and re-verify here.

Status: PENDING USER VERIFICATION

---

## Phase I Issue #27 — Connection badge + Reconnect dialog

Pure connection core (`src/lib/blenderConnection.ts`) + React glue
(`src/lib/connectionContext.tsx`, `src/components/ConnectionBadge.tsx`,
App/Editor wiring) committed mocked-only (Blender :9876 unattended-absent
across scheduled fires; same precedent as Phase E/G). The pure core is fully
unit-tested (13 vitest cases: probe normalisation, never-throws, classify,
strict editChainGate, polling immediate/no-overlap/unmount-race/stop). The
three acceptance bullets require a real Blender + BlenderMCP session and are
the only thing not exercised by the mocked suite.

Steps (run with `pnpm tauri dev`):
1. Start Blender 4.2+, open the BlenderMCP N-panel, click "Connect to Claude"
   (port 9876 listening). Launch the app; reach any screen.
2. Confirm the bottom-right badge goes green ("Blender: connected") within 5s.
3. Quit Blender (or click Disconnect in the addon).
4. Open the Editor screen with a generated GLB selected.

Acceptance:
- Badge turns red ("Blender: disconnected") within 5s of quitting Blender.
- Reopen Blender, click "Connect to Claude", press Reconnect in the badge
  modal (or wait one 5s poll) -> badge goes green within 5s.
- While red, the Editor "Apply" button is disabled and shows the amber
  "Blender is not connected..." message; clicking Apply never runs the
  edit chain. While green, Apply works normally.

Status: PENDING USER VERIFICATION
