# Initial Issue List

Ordered by build phase. Each issue is one PR. Do not skip ahead — phases compound.

---

## Phase A — Tauri skeleton

### #1 — Scaffold Tauri + React + Vite

**Goal:** `cargo tauri dev` opens a window showing "VasePipe v0.0.1". `cargo tauri build` produces `VasePipe-Setup.exe`.

**Tasks**
- `pnpm create tauri-app` → React + TypeScript + Vite template
- Set product name, identifier (`com.vasepipe.app`), window size (1280x800)
- Replace boilerplate with a single centered `<h1>` showing version
- Configure NSIS bundler in `tauri.conf.json` (Windows-only target)
- Verify the produced installer runs on a clean machine

**Acceptance**
- [ ] `pnpm install` clean
- [ ] `cargo tauri dev` opens window with "VasePipe v0.0.1"
- [ ] `cargo tauri build` produces `src-tauri/target/release/bundle/nsis/VasePipe-Setup.exe`
- [ ] Installer runs, app launches, window appears

---

## Phase B — Sidecar plumbing

### #2 — Pure-Python echo sidecar over stdio JSON-RPC

**Goal:** A minimal Python script that reads JSON-RPC requests from stdin and writes responses to stdout. No `bpy` yet.

**Tasks**
- Create `sidecar/main.py` with a JSON-RPC 2.0 dispatch loop
- Register one command: `system.ping → {ok: true, msg: "pong"}`
- Newline-delimited messages
- Add `sidecar/pyproject.toml` (Python 3.11)

**Acceptance**
- [ ] `python sidecar/main.py` then paste `{"jsonrpc":"2.0","id":1,"method":"system.ping"}\n` → get pong back
- [ ] Unknown method returns proper JSON-RPC error object

### #3 — Wire Tauri to spawn the sidecar and call `system.ping` on startup

**Tasks**
- Declare sidecar in `tauri.conf.json` `bundle.externalBin`
- `src-tauri/src/sidecar.rs`: spawn process, wire stdin/stdout, expose `invoke_sidecar(method, params)` to the frontend via Tauri command
- Frontend calls `system.ping` on mount, displays response

**Acceptance**
- [ ] App startup shows "Sidecar: pong" instead of "loading"

### #4 — Add `bpy` to the sidecar and report version

**Tasks**
- Add `bpy==4.2.x` to `pyproject.toml`
- Update `system.ping` to also return `bpy_version`
- Document install pain points in HANDOFF.md (wheel size, Python version requirement)

**Acceptance**
- [ ] App startup shows "bpy 4.x.x ready"
- [ ] `python -c "import bpy; print(bpy.app.version_string)"` works in sidecar's venv

### #5 — Bundle sidecar as `sidecar.exe` via PyInstaller

**Tasks**
- `scripts/build-sidecar.ps1` runs `pyinstaller --onefile --collect-all bpy main.py`
- Test the resulting `sidecar.exe` standalone (no Python install needed)
- Update `tauri.conf.json` to point at the produced exe
- `cargo tauri build` produces a working installer that includes the sidecar

**Acceptance**
- [ ] Built installer runs on a clean Win11 VM with no Python installed
- [ ] App still shows "bpy 4.x.x ready"

---

## Phase C — Mock pipeline

### #6 — Five-screen routing skeleton

**Tasks**
- React Router (or Tanstack Router) with routes for the 5 screens
- Each screen renders a placeholder ("New Project — coming soon") + a `Next` button to advance
- Top-level state machine in `lib/projectState.ts` (current screen, project draft)

**Acceptance**
- [ ] Click through all 5 screens via the Next buttons

### #7 — Mock Meshy commands in sidecar

**Tasks**
- `meshy.generate_preview` returns a fake task_id
- `meshy.poll_task` returns SUCCEEDED on the third call, with URLs pointing at `tests/fixtures/sample_vase.glb`
- `meshy.refine` similar
- Source the fixture GLB from a previous Meshy run (1-2 MB)

**Acceptance**
- [ ] Frontend `Generate` screen polls and lands on `PreviewPick` with a thumbnail
- [ ] No network calls

### #8 — Three.js GLB preview component

**Tasks**
- `<ThreePreview src={glbPath} />` using `@react-three/fiber` + `useGLTF`
- Auto-frames the loaded mesh
- Handles GLB reload (file path changes → new mesh)

**Acceptance**
- [ ] PreviewPick screen shows the fixture GLB rendered in 3D
- [ ] Editor screen shows the same GLB

### #9 — Mock `edit.apply_chain` and Editor wiring

**Tasks**
- Sidecar mock returns the same fixture + a stub sanity report
- Editor's parameter form wired to `edits` list in state
- Apply button calls `edit.apply_chain` and reloads the preview
- Sanity panel renders the 4 lights from the response

**Acceptance**
- [ ] Full click-through Prompt → Preview → Editor → Export in < 20 s using mocks only

---

## Phase D — Real Blender ops

### #10 — Port `voxel_remesh` and `keep_largest_component`

**Tasks**
- Translate from `docs/pipeline.md` Phase 6
- Pure function: takes path, applies op, writes new GLB, returns dims/sanity
- pytest covers a known-good fixture

**Acceptance**
- [ ] Test passes against `sample_vase.glb`
- [ ] Output mesh: 1 component, 0 boundary edges

### #11 — Port `scale_to_height`, `recenter_xy`, `flat_bottom`

**Acceptance**
- [ ] Output dims match target height ± 0.1mm
- [ ] Bottom Z is 0 ± 0.001mm
- [ ] Bounding box centered at X=0, Y=0

### #12 — Port `fix_normals` (volume-sign check + flip if negative)

**Acceptance**
- [ ] Signed volume positive after this op for any input

### #13 — Port `open_top` + `bridge_top_loops`

**Acceptance**
- [ ] Input watertight → Output watertight
- [ ] Top has been opened and bridged (no boundary edges)

### #14 — Port `color_split` (zebra and quarter modes via Boolean Intersect)

**Tasks**
- Zebra: bisect into N horizontal bands, alternate red/yellow, group into 2 objects, apply materials
- Quarter: 4 cutter cubes via Boolean EXACT, intersect each band, regroup

**Acceptance**
- [ ] Zebra count=8: 2 output meshes, both manifold, total volume within 1% of input
- [ ] Quarter: 4 wedges per color (8 outputs), each manifold, volume sum within 1%

### #15 — Wire real `edit.apply_chain` end-to-end

**Tasks**
- Replace mock in `orchestrator.py` with real ops
- Each chain run writes `<project>/preview.glb` for the frontend
- Sanity output reflects real measurements

**Acceptance**
- [ ] Frontend Editor produces real results from fixture GLB
- [ ] Apply round-trip < 5 s for a 50k-poly mesh

---

## Phase E — Real Meshy

### #16 — Settings screen + keyring storage for Meshy key

**Tasks**
- Settings dialog accessible from app menu
- "Meshy API key" field, saved via `keyring.set_password("vasepipe", "meshy_api_key", value)`
- `system.health` reports `meshy_key_set: true/false`
- First-run modal if key missing

**Acceptance**
- [ ] Save key, restart app, `system.health` reports key present
- [ ] Wipe key via `cmdkey /delete:vasepipe` → first-run modal reappears

### #17 — Real Meshy API client

**Tasks**
- `sidecar/meshy.py`: replace mocks with real HTTPS calls
- Polling: 10 s interval, 5 min cap (matches pipeline doc)
- `meshy.download_glb`: streaming download with size verification
- Surface API errors verbatim — no auto-retry

**Acceptance**
- [ ] Real prompt produces a real GLB
- [ ] Block `assets.meshy.ai` in hosts → error shown verbatim, no retry
- [ ] Refine flow uses preview_task_id correctly

---

## Phase F — Export + slicer launch

### #18 — `export.stl` writes per-color STLs

**Tasks**
- `sidecar/pipeline/export_stl.py` ports the binary STL export from pipeline doc
- Color split none → 1 STL; zebra → 2; quarter → 8
- All filenames share the project's run timestamp stem

**Acceptance**
- [ ] STL files appear under `<project>/` with predictable names
- [ ] Each STL is binary (header doesn't start with `solid`), mm units

### #19 — `slicer.launch` for Bambu Studio

**Tasks**
- `sidecar/slicer.py`: spawns Bambu Studio with file args
- Reads slicer path from settings; if missing, returns error code that frontend handles by opening Settings
- Persist resolved path

**Acceptance**
- [ ] Hitting Export opens Bambu Studio with all STLs loaded
- [ ] If path missing, settings dialog appears, user browses, retry succeeds

---

## Phase G — Persistence

### #20 — `<name>.vasepipe.json` save/load

**Tasks**
- Schema in `lib/types.ts` mirrored by `sidecar/orchestrator.py`
- Save: writes JSON + copies artifacts to sibling folder
- Load: re-runs edit chain, restores Editor state

**Acceptance**
- [ ] Save → close app → open project file → byte-identical preview GLB and STLs
- [ ] Schema versioning in place (`version: 1`)

---

## Phase H — Polish + ship

### #21 — App icon, splash, About dialog

**Acceptance**
- [ ] Custom icon visible in installer, taskbar, alt-tab
- [ ] About dialog shows version + build date

### #22 — Crash handler + structured logging

**Tasks**
- Sidecar stderr piped to `%LOCALAPPDATA%\VasePipe\logs\<timestamp>.log`
- "Copy diagnostic" button copies last 200 log lines + project state to clipboard

**Acceptance**
- [ ] Force a sidecar crash; log file contains stack trace
- [ ] User can copy diagnostic and paste into a bug report

### #23 — Final acceptance run

Run the full checklist in `PROMPT.md` § 9 on a clean Win11 VM. Tag v1.0.0 if all green.

---

## Out of v1 (parking lot)

- Real-time live editing (drag = update)
- Paint regions on viewport (Bambu-Studio-style brush)
- In-app slicing / G-code preview
- Multiple generators (Hyper3D, Hunyuan3D)
- Multi-printer profiles
- macOS / Linux
- Auto-update
- Telemetry + crash reporting service
- Project gallery / cloud sync
