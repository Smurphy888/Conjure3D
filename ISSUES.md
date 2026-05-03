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

## Phase B — Thin sidecar plumbing

### #2 — Pure-Python JSON-RPC echo sidecar

**Goal:** A minimal Python script reads JSON-RPC requests from stdin and writes responses to stdout. Newline-delimited.

**Tasks**
- Create `sidecar/main.py` with a JSON-RPC 2.0 dispatch loop
- Register one command: `system.ping → {ok: true, msg: "pong"}`
- Add `sidecar/pyproject.toml` (Python 3.11, deps: `requests`, `keyring`)

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

### #4 — Bundle thin sidecar as `sidecar.exe` via PyInstaller

**Tasks**
- `scripts/build-sidecar.ps1` runs `pyinstaller --onefile main.py` (NO bpy, no `--collect-all` heaviness — just `requests`, `keyring`, stdlib)
- Test the resulting `sidecar.exe` standalone (no Python install needed)
- Update `tauri.conf.json` to reference the produced exe
- `cargo tauri build` produces a working installer including the sidecar

**Acceptance**
- [ ] Built installer runs on a clean Win11 VM with no Python installed
- [ ] App still shows "Sidecar: pong"
- [ ] Installer size < 75 MB

---

## Phase C — First-run wizard

### #5 — Wizard scaffolding + state persistence

**Tasks**
- New route `/wizard` that runs on first launch (or whenever `settings.json` is missing/incomplete)
- 5-step linear flow with "Back" / "Next" buttons; each step renders a child component from `WizardSteps/`
- State persists to `%LOCALAPPDATA%\VasePipe\settings.json` after each successful step (so closing app mid-wizard resumes where you left off)

**Acceptance**
- [ ] First launch shows wizard
- [ ] Subsequent launches skip wizard if all 5 steps green
- [ ] Force re-run via app menu

### #6 — `wizard.detect_blender`

**Tasks**
- Sidecar command checks default install path, Microsoft Store, registry
- Returns `{found, path, version}`
- Frontend step 1: shows result, "Re-check" button if not found, "Download Blender LTS" button (opens browser)

**Acceptance**
- [ ] Detection succeeds on a machine with Blender 4.2+ at default path
- [ ] Returns `found: false` cleanly on a machine without Blender
- [ ] Version string parses correctly

### #7 — Bundle BlenderMCP addon as `resources/blender_mcp_addon.zip`

**Tasks**
- `scripts/package-addon.ps1` zips the BlenderMCP addon source from a known location
- Tauri resource registration so the zip ships in the installer
- Sidecar exposes `wizard.install_addon` that extracts the zip into `%APPDATA%\Blender Foundation\Blender\<version>\scripts\addons\`

**Acceptance**
- [ ] Zip embedded in installer
- [ ] After install, the addon files appear in the user's Blender addons dir
- [ ] Blender's Edit → Preferences → Add-ons shows BlenderMCP enabled (manual user step OK in v1)

### #8 — `wizard.test_socket`

**Tasks**
- Sidecar command opens TCP to `127.0.0.1:9876`, sends a no-op ping, validates response
- Returns `{connected, error?}`
- Frontend step 3: instructs user to click "Connect to Claude" in Blender's BlenderMCP tab; "Test connection" button on success → green check

**Acceptance**
- [ ] Returns connected=true when Blender + addon are running and connected
- [ ] Returns descriptive error otherwise (timeout vs refused vs no addon)

### #9 — `wizard.detect_bambu` + Meshy key entry

**Tasks**
- Detect Bambu Studio at default path; if missing, file browse dialog
- Frontend step 5: password input for Meshy key, calls `system.set_meshy_key`
- Persist Bambu path to `settings.json`

**Acceptance**
- [ ] Bambu detected on machines with default install
- [ ] Meshy key written to Windows Credential Manager (verify with `cmdkey /list`)
- [ ] Wizard hits "All set" screen; New Project route accessible

---

## Phase D — Mock pipeline

### #10 — Five-screen routing skeleton (post-wizard)

**Tasks**
- React Router (or Tanstack Router) with routes for the 5 main screens + wizard
- Each screen renders a placeholder + a `Next` button
- Top-level state machine in `lib/projectState.ts`

**Acceptance**
- [ ] Click through Wizard → New Project → Generate → PreviewPick → Editor → Export

### #11 — Mock Meshy commands in sidecar

**Tasks**
- `meshy.generate_preview` returns a fake task_id
- `meshy.poll_task` returns SUCCEEDED on the third call, with URLs pointing at `tests/fixtures/sample_vase.glb`
- `meshy.refine` similar
- Source the fixture GLBs from real Meshy runs (vase + guitar — both bundled)

**Acceptance**
- [ ] Frontend `Generate` screen polls and lands on `PreviewPick` with a thumbnail
- [ ] No network calls

### #12 — Three.js GLB preview component

**Tasks**
- `<ThreePreview src={glbPath} />` using `@react-three/fiber` + `useGLTF`
- Auto-frames the loaded mesh
- Handles GLB reload (file path changes → new mesh)

**Acceptance**
- [ ] PreviewPick screen shows the fixture GLB rendered in 3D
- [ ] Editor screen shows the same GLB
- [ ] Switching fixtures (vase → guitar) triggers re-render correctly

### #13 — Mock `edit.apply_chain` and Editor wiring

**Tasks**
- Sidecar mock returns the fixture + a stub sanity report
- Editor parameter form wired to `edits` list in state
- Apply button calls `edit.apply_chain` and reloads the preview
- Sanity panel renders the 4 lights from the response

**Acceptance**
- [ ] Full click-through Wizard → Prompt → Preview → Editor → Export in < 30 s using mocks only

---

## Phase E — Real Blender ops via MCP

### #14 — `blender_client.py` TCP socket client

**Tasks**
- Async TCP client: connect to `:9876`, send JSON, read JSON response
- Wraps `execute_blender_code` with reasonable timeout (30s default, 120s for heavy ops)
- Reconnect on connection loss with retry budget (3 attempts, exponential backoff)

**Acceptance**
- [ ] Sends a Python snippet, receives `print()` output back
- [ ] Detects socket close, surfaces "BlenderConnectionError"

### #15 — Port `voxel_remesh` and `keep_largest_component` ops

**Tasks**
- Translate from `docs/pipeline.md` Phase 6
- Each op = a Python source string template with parameter substitution
- Sent via `blender_client` to Blender; response includes new mesh stats
- pytest covers both fixtures

**Acceptance**
- [ ] Test passes against `sample_vase.glb` and `sample_guitar.glb`
- [ ] Output mesh: 1 component, 0 boundary edges
- [ ] Voxel remesh on guitar (after scale step from #16) produces < 200k faces (proves scale ordering)

### #16 — Port `scale_to_longest`, `recenter_xy`, `flat_bottom`

**Acceptance**
- [ ] Output longest dim matches target ± 0.1mm
- [ ] Bottom Z is 0 ± 0.001mm
- [ ] Bounding box centered at X=0, Y=0

### #17 — Port `fix_normals` (volume-sign check + flip if negative)

**Acceptance**
- [ ] Signed volume positive after this op for any input

### #18 — Port `decimate`

**Tasks**
- Decimate modifier with COLLAPSE method, target face count param
- Apply modifier, return new face count
- For voxel-remeshed inputs, expected ratio is < 0.1

**Acceptance**
- [ ] Input 2.7M faces → output ≤ 60k (target 50k)
- [ ] Sanity preserved (manifold, single component, normals)

### #19 — Port `open_top` + `bridge_top_loops` (vase-only, gated by object_type)

**Acceptance**
- [ ] When `object_type == "vase"`: top opened, then bridged, output watertight
- [ ] When `object_type == "solid_decorative"`: ops skip cleanly, mesh unchanged

### #20 — Port `color_split` (zebra and quarter modes via Boolean Intersect)

**Tasks**
- Zebra: bisect into N horizontal bands, alternate red/yellow, group into 2 objects, apply materials
- Quarter: 4 cutter cubes via Boolean EXACT, intersect each band, regroup

**Acceptance**
- [ ] Zebra count=8 on vase: 2 output meshes, both manifold, total volume within 1% of input
- [ ] Quarter on vase: 4 wedges per color (8 outputs), each manifold, volume sum within 1%
- [ ] Editor warning shows when user picks Zebra/Quarter and `object_type != vase`

### #21 — Wire real `edit.apply_chain` end-to-end

**Tasks**
- Replace mock in `orchestrator.py` with real op chain dispatch via `blender_client`
- Each chain run writes `<project>/preview.glb` for the frontend
- Sanity output reflects real measurements
- Auto-clean order enforced: scale → voxel → keep largest → recenter → flat bottom → fix normals → decimate → (vase: open_top + bridge) → (color_split)

**Acceptance**
- [ ] Frontend Editor produces real results from both fixture GLBs
- [ ] Apply round-trip < 8 s for a 50k-poly mesh on a typical dev machine

---

## Phase F — Real Meshy

### #22 — Real Meshy API client

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

## Phase G — Export + slicer launch

### #23 — `export.stl` writes per-color STLs

**Tasks**
- `sidecar/ops/export_stl.py` ports the binary STL export from pipeline doc
- Color split none → 1 STL; zebra → 2; quarter → 8
- All filenames share the project's run timestamp stem

**Acceptance**
- [ ] STL files appear under `<project>/` with predictable names
- [ ] Each STL is binary (header doesn't start with `solid`), mm units

### #24 — `slicer.launch` for Bambu Studio

**Tasks**
- `sidecar/slicer.py`: spawns Bambu Studio with file args
- Reads slicer path from settings (set in wizard)
- If path missing at runtime, returns error code that frontend handles by opening Settings

**Acceptance**
- [ ] Hitting Export opens Bambu Studio with all STLs loaded
- [ ] If path missing, settings dialog appears, user browses, retry succeeds

---

## Phase H — Persistence

### #25 — `<name>.vasepipe.json` save/load

**Tasks**
- Schema in `lib/types.ts` mirrored by `sidecar/orchestrator.py`
- Save: writes JSON + copies artifacts to sibling folder
- Load: re-runs edit chain, restores Editor state

**Acceptance**
- [ ] Save → close app → open project file → byte-identical preview GLB and STLs
- [ ] Schema versioning in place (`version: 1`)

---

## Phase I — Polish + ship

### #26 — Connection badge + Reconnect dialog

**Tasks**
- Status bar shows green/red Blender socket badge, polls `wizard.test_socket` every 5 s
- Click the badge → modal with "Reconnect" button + instructions
- Block edit chain runs when red

**Acceptance**
- [ ] Quit Blender mid-session → badge goes red within 5 s
- [ ] Reopen Blender, click Connect to Claude → badge goes green
- [ ] Editor Apply blocked while red, with clear message

### #27 — App icon, splash, About dialog

**Acceptance**
- [ ] Custom icon visible in installer, taskbar, alt-tab
- [ ] About dialog shows version + build date

### #28 — Crash handler + structured logging

**Tasks**
- Sidecar stderr piped to `%LOCALAPPDATA%\VasePipe\logs\<timestamp>.log`
- "Copy diagnostic" button copies last 200 log lines + project state to clipboard

**Acceptance**
- [ ] Force a sidecar crash; log file contains stack trace
- [ ] User can copy diagnostic and paste into a bug report

### #29 — Final acceptance run

Run the full checklist in `PROMPT.md` § 9 on a clean Win11 VM (one with Blender pre-installed, one without). Tag v1.0.0 if all green.

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
- Auto-installer for Blender (the wizard currently links the user to the Blender download page)
