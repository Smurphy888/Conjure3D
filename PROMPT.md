# Conjure3D — Build Prompt

**Paste the contents of this file into a fresh Claude Code session running with this repo as the working directory.** The agent will read `docs/pipeline.md` as ground truth for the geometry operations.

---

You are building **Conjure3D** — a standalone Windows desktop app that turns a text description into a sliceable 3D-print file. Object-agnostic: vases, decorative figurines, flat parts — anything the user can describe that fits within a 256 mm cube on the X1C build plate. Built for "you + a few family/friends" — meaning the install must work cleanly on a machine you've never seen, with a wizard that detects/installs prerequisites. Ships as a Windows installer (`Conjure3D-Setup.exe`) that installs the app + a thin Python sidecar; user double-clicks an icon to launch.

The app is a UI wrapper around an already-proven pipeline documented in `docs/pipeline.md`. That pipeline is the ground truth for what each stage does — port the Python operations from it verbatim where possible.

The two GLBs in `sidecar/tests/fixtures/` (`sample_vase.glb`, `sample_guitar.glb`) are **diverse-shape test fixtures**, not the product target. They exercise the vase-specific path (open_top + bridge) and the non-vase path (skip both). Both must pass end-to-end.

Read `docs/pipeline.md`, `README.md`, and `HANDOFF.md` before writing any code.

## 1. Architecture

```
  ┌──────────────────────────────┐  invoke()    ┌─────────────────────┐
  │  Tauri shell (Rust)          │ ───────────► │  Python sidecar     │       TCP :9876
  │  + React/TS frontend         │ ◄─────────── │  (stdio JSON-RPC,   │ ───────────────►  ┌────────────────────┐
  │  + Three.js 3D preview       │   response   │   thin — no bpy)    │                   │  Blender 4.2+ LTS  │
  └──────────────┬───────────────┘              │   + requests        │ ◄─────────────── │  + BlenderMCP addon│
                 │                              │   + keyring         │   results        │  (user-installed)  │
                 │                              └─────────┬───────────┘                   └────────────────────┘
            user actions                            HTTPS │  spawn
                                                          ▼
                                          ┌─────────────────────────┐
                                          │ Meshy API   Bambu Studio│
                                          └─────────────────────────┘
```

- Tauri Rust process owns the window, frontend, and lifecycle of the sidecar.
- Sidecar is one long-running Python process started at app launch. **It does NOT bundle Blender.** It speaks JSON-RPC to the frontend (stdio) and TCP-JSON to Blender's BlenderMCP addon (port 9876).
- Geometry ops are written as Python source code in the sidecar and sent as strings to BlenderMCP's `execute_blender_code` command — Blender executes them in its embedded interpreter.
- Frontend renders 3D previews via Three.js loading the GLB the sidecar writes after each edit chain replay.
- Bambu Studio is launched as an external process when the user hits Export; the app does not embed slicing.

## 2. Tech stack (locked)

- Tauri 2.x (Rust shell, Wry webview)
- React 18 + TypeScript + Vite
- Three.js + @react-three/fiber for the 3D preview
- Python 3.11
- `requests` for Meshy
- `keyring` for storing the Meshy API key in Windows Credential Manager
- Standard library `socket` / `asyncio` for BlenderMCP TCP client
- Bundled into a single Windows installer via Tauri's NSIS bundler; Python sidecar pre-built with PyInstaller into `sidecar.exe` (~10 MB) and listed in `tauri.conf.json` as an external binary
- BlenderMCP addon `.zip` is bundled into installer resources and copied to user's Blender addon dir by the first-run wizard

External runtime dependencies (the **user** installs these; wizard handles detection/onboarding):

- Blender 4.2 LTS or newer
- Bambu Studio

## 3. Repo layout

```
conjure3d/
├── src-tauri/                       # Tauri Rust shell
│   ├── Cargo.toml
│   ├── tauri.conf.json              # bundle config, sidecar + addon zip declared
│   ├── build.rs
│   └── src/
│       ├── main.rs                  # window setup
│       └── sidecar.rs               # spawn + JSON-RPC loop
├── src/                             # React + TS frontend
│   ├── main.tsx, App.tsx
│   ├── routes/
│   │   ├── Wizard.tsx               # screen 0 (first-run: Blender detect, addon install, connect)
│   │   ├── NewProject.tsx           # screen 1
│   │   ├── Generate.tsx             # screen 2 (Meshy poll)
│   │   ├── PreviewPick.tsx          # screen 3 (refine/regen/accept)
│   │   ├── Editor.tsx               # screen 4 (param panel + 3D)
│   │   └── Export.tsx               # screen 5 (STL + Bambu launch)
│   ├── components/
│   │   ├── ParamForm.tsx, EditPanel.tsx, SanityPanel.tsx
│   │   ├── ThreePreview.tsx, ProgressBar.tsx
│   │   ├── ConnectionBadge.tsx      # shows Blender socket status
│   │   └── WizardSteps/             # one component per wizard step
│   ├── lib/
│   │   ├── ipc.ts                   # typed Tauri invoke wrappers
│   │   ├── project.ts               # load/save .conjure3d.json
│   │   ├── slugify.ts               # file-stem sanitization (TS twin of sidecar/slugify.py)
│   │   └── types.ts                 # shared TS types (mirror Python schema)
│   └── styles.css
├── sidecar/                         # Python sidecar (becomes sidecar.exe)
│   ├── pyproject.toml
│   ├── main.py                      # JSON-RPC dispatcher, command registry
│   ├── blender_client.py            # TCP client to BlenderMCP :9876
│   ├── meshy.py                     # API client (generate, poll, refine, dl)
│   ├── orchestrator.py              # replay full edit chain on demand
│   ├── wizard.py                    # Blender detect, addon install, connection test
│   ├── slugify.py                   # file-stem sanitization (Python twin of lib/slugify.ts)
│   ├── ops/                         # Python source for each Blender op (sent over the wire)
│   │   ├── __init__.py
│   │   ├── import_glb.py
│   │   ├── voxel_remesh.py
│   │   ├── keep_largest.py
│   │   ├── normalize.py             # scale, recenter, flat bottom
│   │   ├── decimate.py
│   │   ├── fix_normals.py
│   │   ├── top_opening.py           # vase-only
│   │   ├── color_split.py           # zebra + quartering via Boolean
│   │   ├── sanity.py                # manifold/components/normals/dims
│   │   └── export_stl.py
│   ├── slicer.py                    # Bambu Studio launcher
│   ├── settings.py                  # settings.json + keyring access
│   ├── resources/
│   │   └── blender_mcp_addon.zip    # the BlenderMCP addon to install at first run
│   └── tests/
│       ├── test_pipeline.py         # pytest, runs against fixture GLBs
│       ├── test_meshy_mock.py
│       ├── test_slugify.py
│       ├── test_wizard.py
│       └── fixtures/
│           ├── sample_vase.glb      # 1.6 MB diverse-shape test fixture (vase-shaped)
│           └── sample_guitar.glb    # 0.8 MB diverse-shape test fixture (guitar-shaped, asymmetric)
├── docs/
│   └── pipeline.md                  # ground truth for geometry ops
├── scripts/
│   ├── build-sidecar.ps1            # PyInstaller → sidecar.exe (no bpy, fast)
│   ├── package-addon.ps1            # zip the BlenderMCP addon for bundling
│   └── build-installer.ps1          # full release build
├── README.md
├── HANDOFF.md
└── .gitignore
```

## 4. Build phases (do them in this order)

Each phase ends with a working app you can double-click. Don't skip ahead; parallel work tempts integration bugs.

### Phase A — Hello, Tauri (~½ day)
- Scaffold Tauri + React app. `App.tsx` shows "Conjure3D v0.0.1".
- `cargo tauri dev` opens a window. `cargo tauri build` produces a setup .exe.
- **Acceptance:** `Conjure3D-Setup.exe` in `src-tauri/target/release/bundle/nsis/` installs and launches.

### Phase B — Thin sidecar plumbing (~½ day)
- Python sidecar with one command: `system.ping → {ok: true, msg: "pong"}`.
- PyInstaller config that bundles a thin sidecar (no bpy) into ~10 MB exe.
- Tauri spawns it on app launch, sends `system.ping`, displays the response.
- **Acceptance:** UI shows "Sidecar: pong" after launch.
- **STUB FIRST:** before integrating PyInstaller, get JSON-RPC working with a pure-Python sidecar. Each step gets its own commit.

### Phase C — First-run wizard (~2 days)
This is where the "install cleanly on someone else's machine" requirement lives. The wizard is **5 sequential steps**; the user can't reach the New Project screen until all green.

**C.1 — `wizard.detect_blender()`**
Look for Blender in: `C:\Program Files\Blender Foundation\Blender <version>\blender.exe` (default), Microsoft Store install dirs, registry `HKCU\Software\Classes\blendfile\shell\open\command`. Validate executable runs and reports version 4.2+. Returns `{found: bool, path?: str, version?: str}`.

**C.2 — `wizard.install_addon()`**
Locate `%APPDATA%\Blender Foundation\Blender\<version>\scripts\addons\`. Extract the bundled `resources/blender_mcp_addon.zip` into that dir. Write a startup script (or use `bpy` headless via `blender --background --python` to enable the addon) — accepts the user clicking "I clicked Connect to Claude" as confirmation.

**C.3 — `wizard.test_socket()`**
Open TCP connection to `127.0.0.1:9876`. Send a no-op JSON-RPC ping. Confirm response. Returns `{connected: bool, error?: str}`.

**C.4 — `wizard.detect_bambu()`**
Default path: `C:\Program Files\Bambu Studio\bambu-studio.exe`. If not present, prompt user to browse. Persist to settings.

**C.5 — `wizard.set_meshy_key()`**
Frontend collects key via password input. Sidecar saves with `keyring.set_password("conjure3d", "meshy_api_key", value)`. Verify write by reading back.

- **Acceptance:** clean Win11 VM with Blender pre-installed → wizard runs to green; clean Win11 VM without Blender → wizard halts at step 1 with "Install Blender" link, user installs, re-checks, wizard continues.

### Phase D — Local mock pipeline (~1.5 days)
- All 5 main screens render with **fake data only** — no Meshy, no real Blender ops.
- Sidecar commands return canned responses from fixtures:
  - `meshy.generate_preview` returns a fake task_id immediately
  - `meshy.poll_task` returns SUCCEEDED on the third call with URLs that point at `tests/fixtures/sample_vase.glb` (or `sample_guitar.glb` based on a dev toggle)
  - `edit.apply_chain` ignores params, returns the same fixture GLB and a stubbed sanity report
- Three.js preview loads and shows the fixture GLB.
- **Acceptance:** complete user flow click-through Wizard → New Project → Preview → Editor → Export in < 30 s using only fakes. No network, no real Blender ops.

### Phase E — Real Blender ops via MCP (~3 days)
- Implement `ops/*.py` by porting code from `docs/pipeline.md`. Each op is a Python module with a `def code(params: dict) -> str:` function returning a Python source-code string to be sent via MCP socket.
- `blender_client.py`: TCP socket client, sends `{"type":"execute_blender_code","code":"..."}`, parses results.
- `orchestrator.apply_chain`: builds the full code from a list of op invocations, sends in chunks (avoid socket timeouts on long ops), writes intermediate `.preview.glb` for the frontend.
- **Auto-clean ordering — critical:** scale → voxel remesh → keep largest → recenter → flat bottom → fix normals → decimate → (optional open_top for vase) → (optional bridge for vase). Order matters: voxel-remeshing an unscaled 2 m mesh produces 2.7 M faces. Always scale first.
- `pytest sidecar/tests/test_pipeline.py` runs against `sample_vase.glb` AND `sample_guitar.glb` and asserts sanity output (manifold, components==1, dim ≤ 256mm, volume positive). Both fixtures must pass; the guitar is the asymmetric stress test.
- **Acceptance:** Editor in the running app produces real results from both fixture GLBs.

### Phase F — Real Meshy integration (~1 day)
- Replace `meshy.py` mocks with real HTTP calls per `https://api.meshy.ai/openapi/v2/text-to-3d`.
- Key read from `keyring`. Wizard step C.5 ensures it's present.
- Poll loop respects 10 s interval and 5 min cap (matches pipeline doc rule).
- **No silent retries on failure.** Surface error verbatim to UI; a "Try again (will use credits)" button is the only way to retry.
- **Acceptance:** real prompt → real Meshy call → real GLB. Drop in a network kill switch (block `assets.meshy.ai` in hosts file) and verify the error path doesn't auto-retry.

### Phase G — Export + slicer launch (~½ day)
- `export.stl` writes one or many STLs to a project subfolder, named `<slug>_<ts>.stl` (multi-color: `<slug>_<ts>_red.stl` etc.).
- `slicer.launch` runs Bambu Studio with file args. Path read from settings (set in wizard C.4).
- **Acceptance:** export creates files; Bambu Studio opens with the STL(s) loaded.

### Phase H — Persistence (~½ day)
- `<slug>.conjure3d.json` schema in `lib/types.ts` mirrored by `sidecar/orchestrator.py`. Contains: `name` (display), `slug`, `prompt`, `art_style`, `object_type`, `params`, `meshy_task_ids`, `edit_chain`, `artifact_paths`.
- "Save" / "Open" in app menu. Loading restores Editor state and re-runs the edit chain to rebuild the preview GLB.
- **Acceptance:** save a project, close app, reopen, load — same preview, same sanity status, same export output (byte-identical STL).

### Phase I — Polish + ship (~1.5 days)
- App icon, splash screen, About dialog with version + build date.
- Connection badge in status bar (green = Blender socket alive; click to reconnect).
- Crash handler captures sidecar stderr and writes `%LOCALAPPDATA%\Conjure3D\logs\<timestamp>.log`.
- Settings screen accessible from app menu (re-run wizard, change paths, replace Meshy key).
- README screenshots, GIFs of the wizard flow.
- **Acceptance:** ship `Conjure3D-Setup.exe` and a clean Win11 VM install-and-run smoke test for the bundled fixtures.

## 5. Functional requirements per screen

**0 — Wizard:** sequential 5 steps as described in Phase C. User can't skip; "Back" allowed within wizard. Each step shows green check on success, red X with retry button on failure. Persists state — closing the app mid-wizard resumes where you left off.

**1 — New Project:** project name input (free text, the slug derives from this), prompt textarea (multiline, 500-char cap), `art_style` dropdown (realistic / sculpture / low-poly / cartoon), parameter form: `target_height_mm` (10–250, but interpreted as *longest dim*), `object_type` dropdown (vase / solid_decorative / flat_part — affects auto-clean), `flat_bottom` (toggle, default on), `decimate_target_faces` (default 50000), `printer` (X1C only in v1). Hollow handled in slicer per pipeline doc — don't expose a Solidify control; do expose a "Hollow walls in slicer (vase mode)" hint that shows in Export. "Generate" button → screen 2.

**2 — Generate:** progress bar (driven by Meshy `progress` field), elapsed time, Cancel button (DELETE on the Meshy task, then back to screen 1). On SUCCEEDED → screen 3.

**3 — Preview Pick:** thumbnail image fetched from Meshy `thumbnail_url`, three buttons: **Refine** (uses credits — confirm dialog) / **Regenerate** (go back to 1 with prompt prefilled) / **Accept** → screen 4.

**4 — Editor:** left = parameter panel, right = Three.js viewport. Edits as named blocks the user toggles and tunes:
- Auto-clean (always on, gated by `object_type`):
  - All types: scale → voxel remesh @ 0.8 mm → keep largest → recenter → flat bottom @ 1mm → fix normals → decimate to target faces
  - `vase` only: open_top @ 2 mm → bridge top loops
  - `solid_decorative` / `flat_part`: skip top-open and bridge
- Color split (radio): None | Zebra (count 2-16, axis Z default) | Quarter (X+Y planes through center). Show a warning under the radio: "Parametric splits work best on rotationally-symmetric objects (vases, lampshades). For complex anatomies (guitar body / neck / headstock, chess pieces, etc.), select None and use Bambu Studio's brush paint instead."

"Apply" button at bottom; greyed out unless params changed; click → sidecar runs `edit.apply_chain` → frontend reloads `<project>/preview.glb`. Sanity panel under viewport: 4 lights (Manifold / Single component / Normals outward / Longest dim ≤ 256 mm). Red light = warning, blocks Export.

**5 — Export:** lists STL(s) that will be written based on color split. "Export & Open in Bambu Studio" button. Below it, a copy block with the slicer recipe — **shape-aware**: the recipe for `vase` recommends spiral mode; for `solid_decorative` it recommends 15% gyroid infill + brim 5mm if longest dim > 100mm; for `flat_part` it recommends laying flat + 4 perimeters. After export, app shows "Now click Slice → Print in Bambu Studio."

## 6. Sidecar JSON-RPC commands (stable contract)

```jsonc
// Each request: {"jsonrpc":"2.0","id":<int>,"method":"<name>","params":{...}}
// Each response: {"jsonrpc":"2.0","id":<int>,"result":{...}} or {..., "error":{...}}

system.ping              ()                                 → { ok, msg }
system.health            ()                                 → { meshy_key_set, slicer_path,
                                                                blender_path, blender_socket }
system.set_settings      ({ slicer_path?, blender_path? })  → { ok }
system.set_meshy_key     ({ key })                          → { ok }            // writes via keyring

wizard.detect_blender    ()                                 → { found, path?, version? }
wizard.install_addon     ({ blender_version })              → { ok, addon_dir }
wizard.test_socket       ()                                 → { connected, error? }
wizard.detect_bambu      ()                                 → { found, path? }

meshy.generate_preview   ({ prompt, art_style })            → { task_id }
meshy.poll_task          ({ task_id })                      → { status, progress, model_urls?, thumbnail_url? }
meshy.refine             ({ preview_task_id })              → { task_id }
meshy.download_glb       ({ url, dst_path })                → { path, size }

edit.apply_chain         ({ src_glb, edits, dst_dir })      → { preview_glb, stl_paths, sanity, dims_mm, errors? }
edit.list_operations     ()                                 → { ops: [...] }   // for UI to render edit catalog

export.stl               ({ project_dir, slug, color_split })  → { stls: [...] }
slicer.launch            ({ paths })                        → { ok, pid }

project.save             ({ project, dst_path })            → { ok, path }
project.load             ({ path })                         → { project }

util.slugify             ({ name })                         → { slug }         // exposed for UI preview
```

`edits` is an ordered list. Auto-clean order is fixed (scale must run before voxel remesh). Color split is the optional last step:

```jsonc
[
  { "type": "scale_to_longest","target_mm": 80 },
  { "type": "voxel_remesh",   "voxel_mm": 0.8 },
  { "type": "keep_largest" },
  { "type": "recenter_xy" },
  { "type": "flat_bottom",    "cut_mm": 1 },
  { "type": "fix_normals" },
  { "type": "decimate",       "target_faces": 50000 },
  // ↓ vase-only steps (gated by object_type)
  { "type": "open_top",       "cut_mm": 2 },
  { "type": "bridge_top_loops" },
  // ↓ optional color split
  { "type": "color_split",    "mode": "zebra", "count": 8, "axis": "z",
                              "colors": ["red","yellow"] }
]
```

Every edit is a pure function. Replaying the same chain on the same input GLB must produce a byte-identical STL (test this with both fixtures).

## 7. Persistence schema (`<slug>.conjure3d.json`)

```jsonc
{
  "version": 1,
  "name": "Lampshade idea",            // user-typed display name
  "slug": "lampshade-idea",            // sanitized; drives filenames
  "created_at": "2026-04-30T13:29:30Z",
  "prompt": "<full prompt text>",
  "art_style": "realistic",
  "object_type": "vase",               // vase | solid_decorative | flat_part
  "meshy": {
    "preview_task_id": "019ddfde-...",
    "refine_task_id":  "019de194-..." | null
  },
  "params": {
    "target_height_mm": 80,            // longest dim
    "flat_bottom": true,
    "decimate_target_faces": 50000,
    "printer": "X1C"
  },
  "edits": [ /* see above */ ],
  "artifacts": {
    "src_glb":     "lampshade-idea_20260430-132930.glb",
    "preview_glb": "preview.glb",
    "stl_paths":   ["lampshade-idea_20260430-132930.stl"]
  }
}
```

Artifacts live in a sibling folder `<slug>.conjure3d/`. Both the project file and that folder share the slug stem.

## 8. Failure handling rules (from pipeline doc, must be enforced)

- **Meshy fail/timeout** → quote the API error verbatim in the UI, never auto-retry (would re-spend credits). User clicks "Try again" explicitly.
- **Blender socket dead mid-run** → stop, show "Reconnect Blender" dialog, do NOT try to continue or fall back to subprocess. The user must manually click "Connect to Claude" again in Blender's BlenderMCP tab.
- **Blender op error** → catch, log full stderr to log file, show a generic "Edit failed" toast with a "Copy diagnostic" button.
- **GLB imports as empty** → re-import with `import_pack='UNPACK'`; if still empty, show "Mesh appears empty — regenerate?" with the prompt prefilled.
- **Mesh non-manifold after Meshy** → already handled by auto-clean (voxel remesh + keep largest).
- **Voxel remesh runs slow / hangs** → likely the mesh wasn't scaled first. Verify the auto-clean order; if it's correct, drop voxel size to 1.0mm or 1.2mm.
- **Build plate exceeded** → show in sanity panel; do **not** auto-shrink. Block Export until user changes target dim.
- **Bambu Studio binary missing** → prompt for path, persist to settings.

## 9. Acceptance test checklist

Run before tagging v1.0.0:

- [ ] `cargo tauri build` produces `Conjure3D-Setup.exe` < 75 MB
- [ ] Fresh Win11 VM (Blender NOT pre-installed): installer runs; wizard halts at step 1 with install link; after Blender install + re-check, wizard completes
- [ ] Fresh Win11 VM (Blender pre-installed): wizard runs all 5 steps to green
- [ ] `system.ping` returns pong after launch
- [ ] `system.health.blender_socket` reflects current state (green when Blender + addon connected; red when not)
- [ ] `pytest sidecar/tests/` all green
- [ ] Slugify: round-trip "Mom's birthday 2026 ❤️" → `moms-birthday-2026` → matching files appear in Downloads
- [ ] End-to-end with mock Meshy on **vase fixture**: prompt → preview → editor → export → STL file present, opens in Bambu Studio
- [ ] End-to-end with mock Meshy on **guitar fixture**: same, with `object_type: solid_decorative` (open_top / bridge skipped)
- [ ] End-to-end with real Meshy: same as above, with live API. Records task IDs in project file
- [ ] Network kill mid-poll: error shown verbatim, no retry, credits not spent twice
- [ ] Project save/load round-trip: same preview GLB hash, same STL hashes
- [ ] Sanity panel correctly flags a known-bad mesh (drop a non-manifold fixture and assert)
- [ ] Bambu Studio missing → settings prompt → path saved → next export launches successfully
- [ ] Color split = Zebra count=8 produces 2 STLs that re-assemble into the original mesh's bounding box (volume sum within 1% of original)
- [ ] Color split = Quarter produces 4 manifold pieces (`bnd=0, mlt=0, wire=0, vol>0` for each)
- [ ] Blender quit mid-run: Editor shows red Reconnect badge, command returns clean error, no crash

## 10. Cues and gotchas

- **Stub Meshy with a fixture GLB before integrating the API.** Doubles dev speed, lets you iterate the editor against deterministic input.
- **Stub the BlenderMCP socket too** for unit tests. Real Blender lives in integration tests only.
- **Auto-clean order — scale FIRST.** Voxel remesh on an unscaled 2 m Meshy output produces 2.7 million faces. Always: `scale_to_longest` → `voxel_remesh` → ... rest. This was a real bug in the prototype.
- **Decimate is mandatory.** Even with proper scale order, voxel remesh produces 100k+ faces. `decimate target_faces=50000` keeps STLs sane.
- **`open_top` + `bridge` are vase-only.** Gate on `object_type`. For guitars / chess pieces / busts they create holes that ruin the mesh.
- **Slugify both sides (TS + Python) must produce identical output.** Test with the same input set in both `lib/slugify.ts` and `sidecar/slugify.py`. The Python is canonical (used for filenames); the TS exists for live UI preview.
- **Don't run `bpy` in the Tauri Rust process.** Don't even bundle it. The sidecar is thin; Blender lives outside.
- **JSON-RPC over stdio: terminate every message with `\n`.** Tauri's built-in sidecar IPC supports this directly.
- **MCP socket has per-call timeout.** Long ops (heavy voxel remesh) hang the socket. Either pre-scale the mesh or chunk the ops. Auto-clean order solves this for the common case.
- **Three.js loads GLB with `GLTFLoader`** — the GLB you write from Blender must include normals and use plain diffuse materials (no shader nodes) or it'll render gray.
- **Boolean Intersect with EXACT solver** is the right move for quartering. Don't try bisect+fill on multi-component meshes — T-junctions and multi-face edges. Confirmed in the prototype.
- **Volumes won't perfectly conserve across cuts** of dense voxel-remeshed meshes (`bm.calc_volume` precision). Tolerate ±1% in tests, log warnings beyond ±5%.
- **Don't hardcode paths.** Use `%LOCALAPPDATA%\Conjure3D\projects` as default project root; let users override.
- **Tauri 2's NSIS bundler signs only with a real cert.** Ship unsigned for v1 with a clear README note.
- **Don't mention "Solidify" in the UI.** It misbehaves on dense voxel topology. Hollowing is the slicer's job; the UI says so.
- **Color split warning text must show in the Editor** when the user picks Zebra/Quarter on a non-vase shape. The text is in functional spec § Editor.

## 11. Out of scope for v1

- Real-time live editing (slider drag = preview update) — Apply-button only
- Brush/paint color regions — parametric only
- In-app slicing or G-code preview — hand off to Bambu Studio
- Generators other than Meshy — Hyper3D, Hunyuan3D etc. live in BlenderMCP but aren't in v1 surface
- Multi-printer profile picker — X1C hardcoded
- Authentication, telemetry, multi-user, cloud sync
- macOS / Linux builds
- Vase-mode toggle in the app (tell user to flip it in slicer)
- Auto-update

---

Reference: `docs/pipeline.md` (in this repo) is the ground truth for geometry ops. Reuse the Python operations from it verbatim where possible — they get sent to Blender as code via the MCP socket.
