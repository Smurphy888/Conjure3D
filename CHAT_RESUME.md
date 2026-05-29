# Conjure3D — Mid-Build Chat Resume

> Drop-in context for a fresh Claude chat. Read this end-to-end before touching code.
> (The general dev handoff lives in `HANDOFF.md`. This file is specifically for resuming an in-progress chat session.)

## Read these next, in order

1. `PROMPT.md` — original brief
2. `ISSUES.md` — 30 issues / 9 phases (most done)
3. `HANDOFF.md` — general developer handoff
4. `docs/pipeline.md` — canonical auto-clean order, op contracts
5. `docs/manual-blender-tests.md` — live acceptance checklist
6. `C:\Users\Business\Desktop\conjure3d-agent-prompt.txt` — standing autonomous-run policy
7. `git log --oneline -25` inside the worktree

## Worktree

- Path: `C:\Users\Business\Desktop\Project's\Conjure3D\.claude\worktrees\sad-bartik-e11c5a`
- Branch: `claude/sad-bartik-e11c5a`
- HEAD as of this handoff: `eacfabb` (clean tree)

## Latest installer (ready to test)

```
<worktree>\src-tauri\target\release\bundle\nsis\Conjure3D_0.0.1_x64-setup.exe
```
15.32 MB · built 2026-05-26 15:39:28 · contains the persistent-connection workaround (`eacfabb`).

---

## State of play

Phases A–I, issues #1–#29, all committed:

- Phase F — real Meshy text→3D wired end-to-end
- Phase G — Export screen + per-color binary STL + slicer.launch into Bambu Studio
- Phase H — `<slug>.conjure3d.json` project save/load
- Phase I — connection badge, app icon, About dialog, crash handler + structured logging

Only remaining ticket: **#30** — v1.0.0 tag + `docs/manual-blender-tests.md` live verification.

### What we just fixed (eacfabb)

BlenderMCP addon's server thread silently dies after the first heavy main-thread op.
Workaround: one persistent TCP connection held across the whole edit chain.

- `sidecar/blender_client.py` — new `BlenderSession` class, `session_scope()` context manager, thread-local `_tls.session`. `execute_blender_code()` piggybacks on an active session.
- `sidecar/orchestrator.py` — `apply_chain` body wrapped in `with session_scope():` plus outer `try/except BlenderConnectionError` so the JSON-RPC boundary never raises.
- Retry policy bumped to 5 attempts with capped exponential backoff (max 10s).

**Not yet tested against a running Blender.** Live confirmation is the immediate next step.

---

## Immediate next steps (in order)

### 1. Fix the broken orchestrator tests

5 tests in `sidecar/tests/test_orchestrator.py` are failing after the `eacfabb` refactor:

- `test_object_type_inferred_vase_when_open_top_present`
- `test_color_split_chain_marks_single_component_true_despite_multi`
- `test_unknown_edit_recorded_in_errors_not_raised`
- `test_import_failure_returns_structured_error_not_raise`
- `test_op_failure_is_collected_and_chain_continues`

The `_noop_session` patch is present in `_patched()` (around line 58) but isn't taking effect for these — they hit the real `session_scope` and return `"Could not connect to Blender"`. Diagnose why the patch slips (likely an import-binding or patching-order issue), fix, commit. Run the full sidecar suite afterwards.

(Note: `test_dispatch_generate_preview` is a pre-existing stale unrelated to this — task_id format change after real-Meshy wiring. Leave it.)

### 2. User runs the live pipeline

Install the `.exe` above, open Blender 4.2 LTS with BlenderMCP addon enabled, click **"Connect to MCP server"** in the N-panel (port 9876), then run Generate → Edit → Export → Bambu.

Three outcomes:

- **(a) Succeeds end-to-end** → start Phase J: natural-language editor (see below).
- **(b) Addon thread death again** → fork BlenderMCP, vendor under `sidecar/blender_addon/`, fix the server-thread reaping bug.
- **(c) Different failure** → `Editor.tsx` now surfaces `result.errors` cleanly; diagnose from the UI message.

### 3. Phase J — Natural-language editor (after pipeline confirmed)

- Embedded llama.cpp; model **Qwen2.5-Coder-7B-Instruct Q4_K_M GGUF**.
- Downloaded on first run (NOT bundled in the installer).
- Settings: variant picker (3B / 7B / 14B).
- Optional opt-in cloud escape hatch — user supplies their own OpenAI / OpenRouter key. Off by default.

### 4. Phase J completion → Issue #30

Tag `v1.0.0` after `docs/manual-blender-tests.md` is fully verified live.

---

## Hard constraints — do not violate

- **Shipped product MUST NOT use Anthropic tokens.** Build progression may.
- **NEVER log secrets** (Meshy API key, OpenAI key, etc.) to `walkthrough.txt` or anywhere on disk.
- **Soft-delete only.** `rm`, `Remove-Item -Recurse -Force`, `git reset --hard`, `git checkout -- <file>`, `git clean -f/-fdx` are FORBIDDEN unless preceded by snapshotting the target to:
  ```
  C:\Users\Business\Desktop\deleted\<YYYYMMDD-HHMMSS>-<reason>\
  ```
- **One issue per commit, one issue per PR.** Conservative — finish + verify + commit before starting the next.
- **Run tests at each phase boundary.** Don't leave half-states.
- **Ask for permission** before creating any online accounts.
- **Call advisor** before substantive work AND before declaring done.
- The apostrophe in `Project's\` breaks `tauri-winres v0.3.6`. A patched copy is vendored under `src-tauri/vendor/tauri-winres/` with `[patch.crates-io]` in `src-tauri/Cargo.toml`. **Do not undo this.**

---

## Architecture cheat-sheet

- **Frontend:** Tauri 2 + React 18 + TypeScript + Vite. `HashRouter` for webview compatibility. `@react-three/fiber` + drei for preview.
- **Sidecar:** Python, PyInstaller `--onefile`, JSON-RPC over stdio. Fixtures bundled via `--add-data` and resolved with `sys._MEIPASS` when frozen.
- **Blender:** BlenderMCP addon (third-party, `ahujasid/blender-mcp`), TCP socket 127.0.0.1:9876, `execute_code` command.
- **Slicer:** Bambu Studio launched with STL paths on argv.
- **Auth:** Meshy API key stored via `keyring` in Windows Credential Manager.
- **Auto-clean canonical order:** scale → voxel → keep_largest → recenter → flat_bottom → fix_normals → decimate → (vase: open_top + bridge_top_loops) → color_split.

## Build commands (proven)

```
scripts\build-sidecar.ps1            # PyInstaller sidecar.exe -> src-tauri/resources/
pnpm tauri build                     # Full installer (worktree root)
```

Autonomous loop wrapper: `C:\Users\Business\Desktop\conjure3d-fire.ps1` (uses `--model opus`, pipes prompt via stdin — not `-p`, because `claude.exe` parses embedded `--flag` text as a CLI flag).

## Recent commits

```
eacfabb fix(blender_client): persistent connection across edit chain (addon-bug workaround)
fe96d59 fix(wizard): correct BlenderMCP button name in Step 3 copy
cf9eea3 feat(export): implement the Export screen (Phase G UI) + register export.stl
397e1c1 fix(editor/preview): surface edit-chain errors; layout clipping; loading bleed
c8775a2 feat(meshy): wire REAL Meshy end-to-end + fix centering (Phase F accepted)
0355527 fix(preview/generate): black screen on generate; mock unusable in installed exe
5b21a91 fix(wizard): Step Continue buttons froze the wizard (event-as-settings bug)
c2a17a7 fix(build): build-sidecar.ps1 aborted on PyInstaller stderr (stale-bundle bug)
90d28b9 Phase I Issue #29: Crash handler + structured logging
1fd0c7e Phase I Issue #28: App icon + About dialog
2269865 Phase I Issue #27: Connection badge + Reconnect dialog
447f8af Phase H Issue #26: <slug>.conjure3d.json save/load
03905f8 Phase G Issue #25: slicer.launch hands STLs to Bambu Studio
75c3f29 Phase G Issue #24: export_stl per-color binary STLs
```

---

## Blender 4.2 vs 5.1 (user asked)

Connection bug was never version-dependent — 5.1 doesn't fix or break it. But the 22+ geometry ops were only mock-tested, not live-tested against any Blender version. **4.2 LTS is the safer first live test.** 5.1 is a non-LTS moving target; retry it after 4.2 succeeds end-to-end. `Editor.tsx` now surfaces op-level failures cleanly, so 5.1 incompatibilities will show in the UI rather than blackscreen.

## Start by

1. `cd` into the worktree, `git log -1` to confirm HEAD = `eacfabb`.
2. Fix the 5 failing orchestrator tests; commit.
3. Wait for the user to report the live Blender pipeline result, then proceed per outcome (a/b/c) above.

Confirm you've read `PROMPT.md`, `ISSUES.md`, `HANDOFF.md`, `docs/pipeline.md`, and the agent-prompt before editing code.
