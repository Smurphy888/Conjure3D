# VasePipe — Developer Handoff

This is for the next dev (or future-you) picking up the project mid-stream. Read [README.md](README.md) first for the user-facing pitch and [docs/pipeline.md](docs/pipeline.md) for the spec of what each pipeline phase does.

## Why these architectural choices

- **Tauri over Electron:** smaller installer (~30 MB shell vs ~100 MB), no Chromium runtime baggage. The bulk of our installer is `bpy`, not the UI.
- **Python sidecar over Rust mesh ops:** `bpy` is the only mature, free library that does voxel remesh + boolean intersect with reliable watertight output. Trimesh and manifold3d cover ~70% of what we need but fall over on Meshy's typical "mesh-soup" output (proven in the prototype pipeline).
- **JSON-RPC over stdio:** standard Tauri pattern, debuggable by `tee`-ing stdout, no port conflicts, no auth needed (process-local).
- **`bpy` from PyPI, not subprocess'd Blender:** simpler bundling, no process startup tax per command, single Python interpreter for the session.
- **Edit chain replay over destructive editing:** every "Apply" replays from the source GLB. Slower per-edit but guarantees determinism + makes save/load trivial (just store the chain, not the mesh state).
- **`keyring` for the Meshy API key:** Windows Credential Manager is encrypted at rest, scoped per user, survives reboots, and is one line of code per read/write. Other options considered: env var (bad UX), plain JSON (bad security), prompt every launch (hostile UX), DPAPI direct (extra code for no UX gain).

## What's done / what isn't

Update this as you go.

- [ ] Phase A — Hello, Tauri (skeleton, build to .exe)
- [ ] Phase B — Sidecar plumbing
- [ ] Phase C — Local mock pipeline
- [ ] Phase D — Real Blender ops
- [ ] Phase E — Real Meshy
- [ ] Phase F — Export + slicer launch
- [ ] Phase G — Persistence
- [ ] Phase H — Polish + ship

## Where to start (cold pickup)

1. Clone the repo. Read `docs/pipeline.md` — that's the spec for what each geometry op does.
2. Run `pnpm install && cargo tauri dev`. App should launch with a stub UI.
3. Run `cd sidecar && python main.py` in a separate terminal. Send a `{"jsonrpc":"2.0","id":1,"method":"system.ping"}\n` to its stdin and confirm you get a pong.
4. Pick the next unchecked phase above. Each phase has explicit acceptance criteria in [PROMPT.md](PROMPT.md) — don't move on until they're met.

## Pitfalls we hit (or expect to hit)

- **Meshy returns "mesh soup" for many prompts.** A single watertight mesh per the prompt is the *intent*, not the *guarantee*. Voxel remesh at 0.8 mm + keep-largest-component is the only reliable way to get to a single watertight mesh. Don't skip this in the auto-clean chain.
- **`bpy` `Solidify` modifier breaks on dense voxel-remeshed topology.** Don't try to do hollow walls inside Blender. Hollowing is the slicer's job (vase mode or wall-count + infill=0).
- **`bpy.ops.mesh.bisect` with `use_fill=True` on multi-component meshes produces T-junction artifacts** (multi-face edges where perpendicular cut planes meet existing component boundaries). Use Boolean Intersect with cutter cubes (EXACT solver) for clean topology when slicing.
- **Volumes don't perfectly conserve across cuts** of dense voxel-remeshed meshes — `bm.calc_volume` has float precision limits. Tolerate ±1% in tests, log warnings beyond ±5%.
- **Three.js GLTFLoader can't display materials without nodes.** Set diffuse colors before exporting the preview GLB or it'll render gray.
- **PyInstaller + bpy needs `--collect-all bpy`** and you may need to exclude `bpy.utils.previews` from the bundle to avoid an import error.
- **Tauri 2's NSIS bundler signs only with a real cert.** Ship unsigned for v1; document the SmartScreen prompt in README.
- **Meshy's signed S3 URLs expire (~24h).** Download the GLB to disk in Phase 4 and store the local path; never re-fetch from the URL later.
- **Blender's signed volume sign depends on normal direction.** A negative volume = inverted normals; flip them before any other op or every downstream check is wrong.

## Testing approach

- `pytest sidecar/tests/` is the workhorse. It runs against a fixture GLB (`tests/fixtures/sample_vase.glb` — borrow from a real Meshy run if you don't have one). Each pipeline op has a unit test asserting the sanity output (manifold, components, dim).
- Frontend has Vitest for `lib/` (project save/load, type schemas).
- The biggest integration test is the "save → close app → reopen → load project → produce byte-identical STL" round-trip. That covers the determinism guarantee.
- For Meshy, mock the HTTP layer with `responses` (Python lib). The real API path is exercised manually before each release; don't run it in CI.

## Key files when investigating bugs

- `sidecar/main.py` — JSON-RPC dispatcher, all command names live here
- `sidecar/orchestrator.py` — edit chain replay (deterministic)
- `sidecar/pipeline/sanity.py` — manifold/components/normals/dims checks
- `src/lib/ipc.ts` — typed wrappers around Tauri invoke; if a command is missing from here it's missing from the type system
- `%LOCALAPPDATA%\VasePipe\logs\<timestamp>.log` — every sidecar stderr + crash report

## Style / conventions

- Python: black + ruff. Tabs nowhere; 4 spaces.
- TS: prettier + eslint. `pnpm lint` before commit.
- Commit messages: short imperative, no Jira tags.
- Never log the Meshy API key. Never log the user's prompt to stderr.

## Releasing

```powershell
.\scripts\build-sidecar.ps1     # PyInstaller → sidecar.exe (~5 min)
cargo tauri build               # bundles UI + sidecar.exe → setup.exe
```

Output: `src-tauri/target/release/bundle/nsis/VasePipe-Setup.exe`. Smoke-test on a clean Windows VM before tagging.
