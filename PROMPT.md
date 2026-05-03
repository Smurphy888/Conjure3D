# VasePipe — Build Prompt

**Paste the contents of this file into a fresh Claude Code session running with this repo as the working directory.** The agent will read `docs/pipeline.md` as ground truth for the geometry operations.

---

You are building **VasePipe** — a standalone Windows desktop app that turns a text description into a sliceable, multi-color 3D-print file with one human checkpoint in the middle and one at the end. Single user, offline except for Meshy API calls. Ships as a Windows installer (`VasePipe-Setup.exe`) that installs the app + its dependencies; user double-clicks an icon to launch.

The app is a UI wrapper around an already-proven pipeline documented in `docs/pipeline.md`. That pipeline is the ground truth for what each stage does — port the Python operations from it verbatim where possible.

Read `docs/pipeline.md`, `README.md`, and `HANDOFF.md` before writing any code.

## 1. Architecture

```
  ┌──────────────────────────────┐  invoke()    ┌─────────────────────┐
  │  Tauri shell (Rust)          │ ───────────► │  Python sidecar     │
  │  + React/TS frontend         │ ◄─────────── │  (stdio JSON-RPC)   │
  │  + Three.js 3D preview       │   response   │  embeds bpy 4.x     │
  └──────────────┬───────────────┘              │  + requests         │
                 │                              └─────────┬───────────┘
                 │                                        │
            user actions                            HTTPS │  spawn
                                                          ▼
                                          ┌─────────────────────────┐
                                          │ Meshy API   Bambu Studio│
                                          └─────────────────────────┘
```

- Tauri Rust process owns the window, frontend, and lifecycle of the sidecar.
- Sidecar is one long-running Python process started at app launch. All geometry work happens here. It exits when the app exits.
- IPC: newline-delimited JSON-RPC 2.0 over the sidecar's stdin/stdout.
- Frontend renders 3D previews via Three.js loading the GLB the sidecar writes after each edit chain replay.
- Bambu Studio is launched as an external process when the user hits Export; the app does not embed slicing.

## 2. Tech stack (locked)

- Tauri 2.x (Rust shell, Wry webview)
- React 18 + TypeScript + Vite
- Three.js + @react-three/fiber for the 3D preview
- Python 3.11
- `bpy` 4.x from PyPI (Blender as a Python module — no Blender install needed)
- `requests` for Meshy
- `keyring` for storing the Meshy API key in Windows Credential Manager
- Bundled into a single Windows installer via Tauri's NSIS bundler; Python sidecar pre-built with PyInstaller into `sidecar.exe` and listed in `tauri.conf.json` as an external binary

Heads up: `bpy` is ~500 MB unpacked. The installer will be ~250 MB compressed. Document this in the README; don't try to slim it for v1.

## 3. Repo layout

```
vasepipe/
├── src-tauri/                       # Tauri Rust shell
│   ├── Cargo.toml
│   ├── tauri.conf.json              # bundle config, sidecar declared here
│   ├── build.rs
│   └── src/
│       ├── main.rs                  # window setup
│       └── sidecar.rs               # spawn + JSON-RPC loop
├── src/                             # React + TS frontend
│   ├── main.tsx, App.tsx
│   ├── routes/
│   │   ├── NewProject.tsx           # screen 1
│   │   ├── Generate.tsx             # screen 2 (Meshy poll)
│   │   ├── PreviewPick.tsx          # screen 3 (refine/regen/accept)
│   │   ├── Editor.tsx               # screen 4 (param panel + 3D)
│   │   └── Export.tsx               # screen 5 (STL + Bambu launch)
│   ├── components/
│   │   ├── ParamForm.tsx, EditPanel.tsx, SanityPanel.tsx,
│   │   ├── ThreePreview.tsx, ProgressBar.tsx
│   ├── lib/
│   │   ├── ipc.ts                   # typed Tauri invoke wrappers
│   │   ├── project.ts               # load/save .vasepipe.json
│   │   └── types.ts                 # shared TS types (mirror Python schema)
│   └── styles.css
├── sidecar/                         # Python sidecar (becomes sidecar.exe)
│   ├── pyproject.toml
│   ├── main.py                      # JSON-RPC dispatcher, command registry
│   ├── meshy.py                     # API client (generate, poll, refine, dl)
│   ├── orchestrator.py              # replay full edit chain on demand
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── import_glb.py            # Phase 5
│   │   ├── voxel_remesh.py          # cleanup non-manifold
│   │   ├── normalize.py             # scale, recenter, flat bottom
│   │   ├── top_opening.py           # bisect + bridge
│   │   ├── color_split.py           # zebra + quartering via Boolean
│   │   ├── sanity.py                # manifold/components/normals/dims
│   │   └── export_stl.py            # Phase 7
│   ├── slicer.py                    # Bambu Studio launcher
│   └── tests/
│       ├── test_pipeline.py         # pytest, runs against fixture GLB
│       ├── test_meshy_mock.py
│       └── fixtures/sample_vase.glb # 1.6 MB test mesh
├── docs/
│   └── pipeline.md                  # ground truth for geometry ops
├── scripts/
│   ├── build-sidecar.ps1            # PyInstaller → sidecar.exe
│   └── build-installer.ps1          # full release build
├── README.md
├── HANDOFF.md
└── .gitignore
```

## 4. Build phases (do them in this order)

Each phase ends with a working app you can double-click. Don't skip ahead; parallel work tempts integration bugs.

### Phase A — Hello, Tauri (~½ day)
- Scaffold Tauri + React app. `App.tsx` shows "VasePipe v0.0.1".
- `cargo tauri dev` opens a window. `cargo tauri build` produces a setup .exe.
- **Acceptance:** `VasePipe-Setup.exe` in `src-tauri/target/release/bundle/` installs and launches.

### Phase B — Sidecar plumbing (~1 day)
- Python sidecar with one command: `system.ping → {pong: true, bpy_version}`.
- PyInstaller config that bundles `bpy` into `sidecar.exe`.
- Tauri spawns it on app launch, sends `system.ping`, displays the response.
- **Acceptance:** UI shows `bpy 4.x.x ready` after launch.
- **STUB FIRST:** before integrating real `bpy`, get JSON-RPC working with a pure-Python sidecar that just echoes. Then add `import bpy`. Then add PyInstaller. Each step gets its own commit.

### Phase C — Local mock pipeline (~2 days)
- All 5 screens render with **fake data only** — no Meshy, no Blender.
- Sidecar commands return canned responses from fixtures:
  - `meshy.generate_preview` returns a fake task_id immediately
  - `meshy.poll_task` returns SUCCEEDED on the third call with URLs that point at `tests/fixtures/sample_vase.glb`
  - `edit.apply_chain` ignores params, returns the same fixture GLB and a stubbed sanity report
- Three.js preview loads and shows the fixture GLB.
- **Acceptance:** complete user flow click-through in < 20 s using only fakes. No network, no Blender. Catches all UI/IPC bugs early.

### Phase D — Real Blender ops in sidecar (~3 days)
- Implement `pipeline/*.py` by porting code from `docs/pipeline.md`.
- Each operation is a pure function: `(input_glb, params) → output_glb`.
- `orchestrator.apply_chain` runs them in order, writes intermediate `.preview.glb` for the frontend.
- `pytest sidecar/tests/test_pipeline.py` runs against `sample_vase.glb` and asserts sanity output (manifold, components==1, dim ≤ 256mm, volume positive).
- **Acceptance:** Editor in the running app produces real results from the fixture GLB. Mock Meshy still in place.

### Phase E — Real Meshy integration (~1 day)
- Replace `meshy.py` mocks with real HTTP calls per `https://api.meshy.ai/openapi/v2/text-to-3d`.
- Key read from Windows credential manager (use `keyring` Python lib). First-run: prompt user for key in Settings, store in keyring.
- Poll loop respects 10 s interval and 5 min cap (matches pipeline doc rule).
- **No silent retries on failure.** Surface error verbatim to UI; a "Try again (will use credits)" button is the only way to retry.
- **Acceptance:** real prompt → real Meshy call → real GLB. Drop in a network kill switch (block `assets.meshy.ai` in hosts file) and verify the error path doesn't auto-retry.

### Phase F — Export + slicer launch (~½ day)
- `export.stl` writes one or many STLs to a project subfolder.
- `slicer.launch` runs Bambu Studio with file args. If binary is missing, prompt user, persist the path to settings.
- **Acceptance:** export creates files; Bambu Studio opens with the STL(s) loaded.

### Phase G — Persistence (~½ day)
- `<name>.vasepipe.json` schema in `lib/project.ts` mirrored by `sidecar/orchestrator.py`. Contains: `prompt`, `art_style`, `params`, `meshy_task_ids`, `edit_chain`, `artifact_paths`.
- "Save" / "Open" in app menu. Loading restores Editor state and re-runs the edit chain to rebuild the preview GLB.
- **Acceptance:** save a project, close app, reopen, load — same preview, same sanity status, same export output (byte-identical STL).

### Phase H — Polish + ship (~1 day)
- App icon, splash screen, About dialog with version + build date.
- Crash handler captures sidecar stderr and writes `%LOCALAPPDATA%\VasePipe\logs\<timestamp>.log`.
- Settings screen: Meshy key, Bambu Studio path, default printer profile.
- README with install instructions and troubleshooting.
- **Acceptance:** ship `VasePipe-Setup.exe` and a clean Win11 VM install-and-run smoke test.

## 5. Functional requirements per screen

**1 — New Project:** prompt textarea (multiline, 500-char cap), `art_style` dropdown (realistic / sculpture / low-poly / cartoon), parameter form: `target_height_mm` (10–250), `flat_bottom` (toggle), `decimate_ratio` (null / slider 0.1–0.9), `printer` (X1C only in v1). Hollow handled in slicer per pipeline doc — don't expose a Solidify control; do expose a "Hollow walls in slicer (vase mode)" hint that shows in Export. "Generate" button → screen 2.

**2 — Generate:** progress bar (driven by Meshy `progress` field), elapsed time, Cancel button (DELETE on the Meshy task, then back to screen 1). On SUCCEEDED → screen 3.

**3 — Preview Pick:** thumbnail image fetched from Meshy `thumbnail_url`, three buttons: **Refine** (uses credits — confirm dialog) / **Regenerate** (go back to 1 with prompt prefilled) / **Accept** → screen 4.

**4 — Editor:** left = parameter panel, right = Three.js viewport. Edits as named blocks the user toggles and tunes:
- Auto-clean (always on, not user-controllable): voxel remesh 0.8 mm, keep largest component, fix normals, scale to target height, recenter, flat bottom 1 mm, open top 2 mm, bridge.
- Color split (radio): None | Zebra (count 2-16, axis Z default) | Quarter (X+Y planes through center).

"Apply" button at bottom; greyed out unless params changed; click → sidecar runs `edit.apply_chain` → frontend reloads `<project>/preview.glb`. Sanity panel under viewport: 4 lights (Manifold / Single component / Normals outward / Longest dim ≤ 256 mm). Red light = warning, blocks Export.

**5 — Export:** lists STL(s) that will be written based on color split. "Export & Open in Bambu Studio" button. Below it, a copy block with the exact filament-assignment / vase-mode / 5-perimeter recipe from the pipeline doc. After export, app shows "Now click Slice → Print in Bambu Studio."

## 6. Sidecar JSON-RPC commands (stable contract)

```jsonc
// Each request: {"jsonrpc":"2.0","id":<int>,"method":"<name>","params":{...}}
// Each response: {"jsonrpc":"2.0","id":<int>,"result":{...}} or {..., "error":{...}}

system.ping              ()                                 → { ok, bpy_version }
system.health            ()                                 → { bpy_ok, meshy_key_set, slicer_path }
system.set_settings      ({ meshy_key?, slicer_path? })     → { ok }

meshy.generate_preview   ({ prompt, art_style })            → { task_id }
meshy.poll_task          ({ task_id })                      → { status, progress, model_urls?, thumbnail_url? }
meshy.refine             ({ preview_task_id })              → { task_id }
meshy.download_glb       ({ url, dst_path })                → { path, size }

edit.apply_chain         ({ src_glb, edits, dst_dir })      → { preview_glb, stl_paths, sanity, dims_mm, errors? }
edit.list_operations     ()                                 → { ops: [...] }   // for UI to render edit catalog

export.stl               ({ project_dir, color_split })     → { stls: [...] }
slicer.launch            ({ paths })                        → { ok, pid }

project.save             ({ project, dst_path })            → { ok, path }
project.load             ({ path })                         → { project }
```

`edits` is an ordered list (the auto-clean steps + zero or one color_split):

```jsonc
[
  { "type": "voxel_remesh",   "voxel_mm": 0.8 },
  { "type": "keep_largest" },
  { "type": "scale_to_height","target_mm": 80 },
  { "type": "recenter_xy" },
  { "type": "flat_bottom",    "cut_mm": 1 },
  { "type": "fix_normals" },
  { "type": "open_top",       "cut_mm": 2 },
  { "type": "bridge_top_loops" },
  { "type": "color_split",    "mode": "zebra", "count": 8, "axis": "z",
                              "colors": ["red","yellow"] }
]
```

Every edit is a pure function. Replaying the same chain on the same input GLB must produce a byte-identical STL (test this).

## 7. Persistence schema (`<name>.vasepipe.json`)

```jsonc
{
  "version": 1,
  "name": "Stylized vase 01",
  "created_at": "2026-04-30T13:29:30Z",
  "prompt": "Stylized minimalist geometric vase, single watertight mesh...",
  "art_style": "realistic",
  "meshy": {
    "preview_task_id": "019ddfde-...",
    "refine_task_id":  "019de194-..." | null
  },
  "params": {
    "target_height_mm": 80,
    "flat_bottom": true,
    "decimate_ratio": null,
    "printer": "X1C"
  },
  "edits": [ /* see above */ ],
  "artifacts": {
    "src_glb":     "vase_20260430-132930.glb",
    "preview_glb": "preview.glb",
    "stl_paths":   ["vase_..._red.stl", "vase_..._yellow.stl"]
  }
}
```

Artifacts live in a sibling folder `<name>.vasepipe/`. Both the project file and that folder share a stem; that pair is what "save" produces.

## 8. Failure handling rules (from pipeline doc, must be enforced)

- Meshy fail/timeout → quote the API error verbatim in the UI, never auto-retry (would re-spend credits). User clicks "Try again" explicitly.
- Blender op error → catch, log full stderr to log file, show a generic "Edit failed" toast with a "Copy diagnostic" button.
- GLB imports as empty → re-import with `import_pack='UNPACK'`; if still empty, show "Mesh appears empty — regenerate?" with the prompt prefilled.
- Mesh non-manifold after Meshy → auto-run voxel remesh at 0.8 mm. Already in the auto-clean chain.
- Build plate exceeded → show in sanity panel; do **not** auto-shrink. Block Export until user changes target_height.
- Bambu Studio binary missing → prompt for path, persist to settings.

## 9. Acceptance test checklist

Run before tagging v1.0.0:

- [ ] `cargo tauri build` produces `VasePipe-Setup.exe` < 300 MB
- [ ] Fresh Win11 VM: installer runs, app launches, no DLL errors
- [ ] `system.ping` returns `bpy 4.x` after launch
- [ ] `pytest sidecar/tests/` all green
- [ ] End-to-end with mock Meshy: prompt → preview → editor → export → STL file present, opens in Bambu Studio
- [ ] End-to-end with real Meshy: same, but with live API. Records task IDs in project file
- [ ] Network kill mid-poll: error shown verbatim, no retry, credits not spent twice
- [ ] Project save/load round-trip: same preview GLB hash, same STL hashes
- [ ] Sanity panel correctly flags a known-bad mesh (drop a non-manifold fixture in `tests/fixtures/bad_mesh.glb` and assert)
- [ ] Bambu Studio missing → settings prompt → path saved → next export launches successfully
- [ ] Color split = Zebra count=8 produces 2 STLs that re-assemble into the original mesh's bounding box (volume sum within 1% of original)
- [ ] Color split = Quarter produces 4 manifold pieces (`bnd=0, mlt=0, wire=0, vol>0` for each)

## 10. Cues and gotchas

- **Stub Meshy with a fixture GLB before integrating the API.** Doubles dev speed, lets you iterate the editor against deterministic input.
- **`bpy` from PyPI works headless on Windows but is finicky.** Use the 4.2 LTS wheel; older wheels miss `wm.stl_export`.
- **Don't run `bpy` in the Tauri Rust process.** Always behind the sidecar process boundary so a Blender crash doesn't take down the UI.
- **JSON-RPC over stdio: terminate every message with `\n`.** Tauri's built-in sidecar IPC supports this directly.
- **Three.js loads GLB with `GLTFLoader`** — the GLB you write from `bpy` must include normals and not rely on textures (set materials to plain diffuse colors before export so the preview shows red/yellow).
- **Boolean Intersect with EXACT solver** is the right move for quartering. Don't try bisect+fill on multi-component meshes — T-junctions and multi-face edges. Confirmed in the existing pipeline run.
- **Volumes won't perfectly conserve across cuts** of dense voxel-remeshed meshes (calc_volume precision). Tolerate ±1% in tests, log warnings beyond ±5%.
- **Don't hardcode paths.** Use `%LOCALAPPDATA%\VasePipe\projects` as the default project root; let users override in Settings.
- **Tauri 2's NSIS bundler signs executables only with a real cert.** For v1 ship unsigned with a clear README note about SmartScreen warnings.
- **PyInstaller + bpy:** add `--collect-all bpy` and exclude `bpy.utils.previews` if it complains. Build sidecar.exe before `tauri build`; the latter just bundles it as a resource.
- **Don't mention "Solidify" in the UI.** It misbehaves on dense voxel topology (we hit this in the original run). Hollowing is the slicer's job; the UI says so.

## 11. Out of scope for v1

- Real-time live editing (slider drag = preview update) — Apply-button only
- Brush/paint color regions — parametric only
- In-app slicing or G-code preview — hand off to Bambu Studio
- Generators other than Meshy — Hyper3D, Hunyuan3D etc. live in Blender MCP but aren't in the v1 surface
- Multi-printer profile picker — X1C hardcoded
- Authentication, telemetry, multi-user, cloud sync
- macOS / Linux builds
- Vase-mode toggle in the app (tell user to flip it in slicer)

---

Reference: `docs/pipeline.md` (in this repo) is the ground truth for geometry ops. Reuse the Python operations from it verbatim where possible.
