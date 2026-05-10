# Conjure3D — Developer Handoff

For the next dev (or future-you) picking up the project mid-stream. Read [README.md](README.md) first for the user-facing pitch and [docs/pipeline.md](docs/pipeline.md) for the spec of what each pipeline phase does.

## What Conjure3D actually is

A desktop app that wraps a generic **text → printable 3D model** pipeline. Users type any description, the app calls Meshy to generate a mesh, drives Blender via socket to clean it up, and hands the result to Bambu Studio for slicing. Object-agnostic: vases, guitars, coasters, figurines, anything that fits the build plate.

The two GLBs in `sidecar/tests/fixtures/` (`sample_vase.glb`, `sample_guitar.glb`) are **diverse-shape test fixtures**, not the product target. They exist to prove the auto-clean handles both a hollow rotational form and a long asymmetric solid — different code paths through the pipeline.

## Architecture choices and why

- **Tauri over Electron** — smaller installer (~30 MB shell vs ~100 MB), no Chromium runtime baggage. Now that Blender is external (not bundled), our installer is dominated by the Python sidecar (~10 MB) — total ~50 MB.
- **External Blender via BlenderMCP socket, not bundled `bpy`** — this is the v1 pivot. The original plan bundled `bpy` (Blender as a Python module) into a 250 MB installer for a fully self-contained app. We chose to require Blender as a user-installed dependency instead because:
  1. The BlenderMCP socket pattern is already proven (used in the prototype runs that informed this app)
  2. Installer drops from 250 MB → 50 MB
  3. Users can SEE the mesh evolving in Blender's viewport, which builds trust and helps debug bad outputs
  4. Updates to Blender don't require a Conjure3D rebuild
  5. The `bpy` PyPI wheel is finicky on Windows (Python version coupling, DLL conflicts)
- **Python sidecar over Rust mesh ops** — the sidecar is now thin (no `bpy`), but we keep Python because:
  - The geometry ops are sent as **Python source code** over the BlenderMCP socket (Blender executes them inside its embedded interpreter)
  - Re-using Python from the prototype is faster than translating to Rust
  - `requests` for Meshy is one-line; `keyring` for credential management is one line
- **JSON-RPC over stdio** between Tauri and sidecar — standard pattern, debuggable, no port conflicts.
- **Edit chain replay over destructive editing** — every "Apply" replays from the source GLB. Slower per-edit but guarantees determinism + makes save/load trivial (just store the chain, not the mesh state).
- **`keyring` for the Meshy API key** — Windows Credential Manager is encrypted at rest, scoped per user, survives reboots, and is one line of code per read/write. Other options considered: env var (bad UX), plain JSON (bad security), prompt every launch (hostile UX), DPAPI direct (extra code for no UX gain).
- **File stems use a sanitized slug + timestamp**, not the raw project name. Keeps filenames human-readable while staying filesystem-safe across Windows path constraints. See `docs/pipeline.md` § "File stem convention" for the slugify rules.

## External runtime dependencies (the user installs these)

| Dependency | Version | How Conjure3D handles it |
|---|---|---|
| Blender | 4.2 LTS or newer | Wizard auto-detects; if missing, opens download page; wizard re-checks. |
| BlenderMCP addon | Bundled .zip in installer | Wizard copies to user's Blender addons dir, enables it, walks user through "Connect to Claude" button. |
| Bambu Studio | Any | Wizard finds default path or asks user to browse. |

Conjure3D expects Blender to be **running and connected** every session. The Editor screen shows a "Blender: Connected" badge in the status bar; if it goes red, the user clicks Reconnect (which retests `:9876`).

## What's done / what isn't

Update this as you go.

- [x] Phase A — Hello, Tauri (skeleton, build to .exe) → `1034c76`
- [x] Phase B — Sidecar plumbing (Issues #2–#5: JSON-RPC echo, Tauri↔sidecar, PyInstaller bundle, slugify Py+TS twins)
- [x] Phase C — First-run wizard (Issues #6–#11: scaffolding, detect_blender, addon bundle, test_socket, detect_bambu+meshy key, five-screen routing)
  - **Follow-up:** Step 2 UI (BlenderMCP addon install) is a stub button; backend `wizard.install_addon` is implemented and tested but the React step lacks real progress feedback. Address in Phase I polish.
- [x] Phase D — Local mock pipeline (Issues #12–#14: mock Meshy, ThreePreview GLB component with drei Bounds + OrbitControls, mock edit.apply_chain + Editor wiring)
- [ ] Phase E — Real Blender ops via MCP (Issues #15–#22)
  - **Status:** queued; gated on user keeping Blender 4.2+ open with BlenderMCP "Connect to Claude" clicked (port 9876 must be LISTENING during fires). Wrapper currently set to `--model opus` for this phase.
- [ ] Phase F — Real Meshy (Issue #23) — agent writes code + mock tests; live API acceptance is user-driven
- [ ] Phase G — Export + slicer launch (Issues #24–#25)
- [ ] Phase H — Persistence (Issue #26)
- [ ] Phase I — Polish + ship (Issues #27–#30)

### Side commits (not part of issue numbering)

- `b5d86b4` — chore: add `protocol-asset` Tauri feature. Needed by ThreePreview to load GLB bytes via Tauri's resource protocol; surfaced during Phase D Issue #13. Not a numbered issue but kept on the main branch since it's required for the feature to function.

## Where to start (cold pickup)

1. Clone the repo. Read `docs/pipeline.md` — that's the spec for what each geometry op does.
2. Make sure you have Blender 4.2+ installed and the BlenderMCP addon loaded. In Blender's N-panel, BlenderMCP tab, click **Connect to Claude**. Verify port 9876 is listening with `netstat -an | findstr 9876`.
3. Run `pnpm install && cargo tauri dev`. App should launch with a stub UI.
4. Run `cd sidecar && python main.py` in a separate terminal. Send a `{"jsonrpc":"2.0","id":1,"method":"system.ping"}\n` to its stdin and confirm you get a pong.
5. Pick the next unchecked phase above. Each phase has explicit acceptance criteria in [PROMPT.md](PROMPT.md) — don't move on until they're met.

## Pitfalls we hit (or expect to hit)

- **BlenderMCP socket dies on Blender restart.** The user's "Connect to Claude" button click is per-Blender-session. App must check the socket on launch and on every command; show "Reconnect" dialog if dead.
- **BlenderMCP addon in `.zip` form needs to be bundled inside the installer's resources** and copied to the user's Blender install at first run. Test on multiple Blender versions (4.2, 4.3, 4.4) — addon manifest varies slightly.
- **Meshy returns "mesh soup" for many prompts.** A single watertight mesh per the prompt is the *intent*, not the *guarantee*. Voxel remesh + keep-largest-component is the only reliable way to consolidate. Don't skip in the auto-clean chain.
- **Voxel remesh runs on whatever-scale mesh you give it.** Meshy's outputs are at arbitrary scale (often 1-2 m per longest dim). At 0.8 mm voxel size on a 2 m mesh, you get **2.7 million faces**. **Always scale the mesh to target dimensions before voxel remesh**, or the face count blows up. Auto-clean order matters: scale → voxel remesh → keep largest → recenter → flat bottom → fix normals → decimate.
- **Auto-clean must include a Decimate step.** Even with proper scale order, voxel remesh on a 200 mm object at 0.8 mm produces 100k+ faces. Decimate to ~50k for sane STLs.
- **`open_top` is vase-specific.** It bisects 2 mm below the top of the mesh and removes the cap. Wrong for guitars, chess pieces, busts, coasters. Gate it on the `object_type` field in MODEL SPEC.
- **`bpy` `Solidify` modifier breaks on dense voxel-remeshed topology.** Don't try to do hollow walls inside Blender. Hollowing is the slicer's job (vase mode or wall-count + infill=0).
- **`bpy.ops.mesh.bisect` with `use_fill=True` on multi-component meshes produces T-junction artifacts** (multi-face edges where perpendicular cut planes meet existing component boundaries). Use Boolean Intersect with cutter cubes (EXACT solver) for clean topology when slicing.
- **Volumes don't perfectly conserve across cuts** of dense voxel-remeshed meshes — `bm.calc_volume` has float precision limits. Tolerate ±1% in tests, log warnings beyond ±5%.
- **Three.js GLTFLoader can't display materials without nodes.** Set diffuse colors before exporting the preview GLB or it'll render gray.
- **Tauri 2's NSIS bundler signs only with a real cert.** Ship unsigned for v1; document the SmartScreen prompt in README.
- **`tauri-winres` v0.3.6 breaks on absolute paths containing apostrophes** (`Project's\…`). Its `escape_string` emits `\'` for an apostrophe, which Microsoft's RC.EXE rejects ("file not found" with the apostrophe escaped as a path separator). We vendor the crate at `src-tauri/vendor/tauri-winres/` with the broken escape removed and wire it through `[patch.crates-io]` in `src-tauri/Cargo.toml`. Keep the patch until upstream fixes it; check periodically against newer tauri-winres releases.
- **Meshy's signed S3 URLs expire (~24h).** Download the GLB to disk in Phase 4 and store the local path; never re-fetch from the URL later.
- **Blender's signed volume sign depends on normal direction.** A negative volume = inverted normals; flip them before any other op or every downstream check is wrong.
- **MCP `execute_blender_code` has a per-call socket timeout.** Long-running ops (heavy voxel remesh on a 2 m mesh) can hang the socket. Either chunk the ops or pre-scale before remesh.
- **Slug collisions are timestamp-resolved.** Two projects named "Vase" produce the same slug; the timestamp differentiates the files. Don't add a uniqueness check on the slug — let timestamps do their job.

## Color split — known limitation

Parametric color splits (zebra / quarter) are designed for vase-shaped objects. For complex anatomies (guitar body / neck / headstock, chess piece base / column / top), the cuts don't follow the natural part boundaries. Surfacing this as an Editor-screen warning and recommending Bambu Studio's brush paint instead is the v1 escape hatch. Brush-paint-in-app is a v2 stretch goal.

## Testing approach

- `pytest sidecar/tests/` is the workhorse. Tests connect to a running Blender + addon, send Python ops, and assert sanity output (manifold, components, dim).
- For tests that don't need a real Blender, mock the MCP socket with a simple in-memory request/response stub.
- Frontend has Vitest for `lib/` (project save/load, type schemas, slugify).
- The biggest integration test is the "save → close app → reopen → load project → produce byte-identical STL" round-trip. Covers the determinism guarantee.
- For Meshy, mock the HTTP layer with `responses` (Python lib). The real API path is exercised manually before each release; don't run it in CI.
- Wizard tests need Blender installed in CI, OR fully mocked steps with a fake socket. Latter is fine for v1.
- **Both fixture GLBs (vase + guitar) must pass end-to-end** — they exercise the vase-only path (open_top + bridge) and the non-vase path (skip both).

## Key files when investigating bugs

- `sidecar/main.py` — JSON-RPC dispatcher, all command names live here
- `sidecar/blender_client.py` — TCP client to BlenderMCP socket on `:9876`
- `sidecar/orchestrator.py` — edit chain replay (deterministic)
- `sidecar/ops/` — Python source for each Blender op (sent over the wire)
- `sidecar/wizard.py` — Blender detect, addon install, connection test
- `sidecar/slugify.py` — file stem sanitization (see pipeline.md for spec)
- `src/lib/ipc.ts` — typed wrappers around Tauri invoke; if a command is missing from here it's missing from the type system
- `%LOCALAPPDATA%\Conjure3D\logs\<timestamp>.log` — every sidecar stderr + crash report

## Style / conventions

- Python: black + ruff. Tabs nowhere; 4 spaces.
- TS: prettier + eslint. `pnpm lint` before commit.
- Commit messages: short imperative, no Jira tags.
- Never log the Meshy API key. Never log the user's prompt to stderr.

## Releasing

```powershell
.\scripts\build-sidecar.ps1     # PyInstaller → sidecar.exe (~30 sec; thin sidecar, no bpy)
cargo tauri build               # bundles UI + sidecar.exe + addon.zip → setup.exe
```

Output: `src-tauri/target/release/bundle/nsis/Conjure3D-Setup.exe`. Smoke-test on a clean Windows VM with Blender pre-installed before tagging.
