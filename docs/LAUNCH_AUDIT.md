# Conjure3D — Launch-Readiness Audit

**Scope:** full-stack review for a commercial launch at scale (thousands→millions of users), across architecture, security, product, UX, QA, and growth.

---

## Status update — 2026-07-02 (verification + hardening pass)

Landed since the original audit (each verified by the full 394-test suite,
`cargo check`, and a production `pnpm build`):

| Item | Status | Commit |
|------|--------|--------|
| S1 — `system.open_url` http/https scheme guard | ✅ landed + tested | `ea87fff` |
| S4 — zip-slip guard in addon install | ✅ landed + tested | `fb85558` |
| S5 — persisted-chain re-validation on load | ✅ landed + tested (UI wiring of `edits_valid` still TODO) | `6d8f852` |
| S3 — pinned SHA-256 on default GGUF download | ✅ landed + tested — published HF LFS hash `509287f7…894d3c`, cross-checked byte-for-byte against a real downloaded file | `f8a0711` |
| §3.1 (partial) — IPC read timeout + dead-process detection | ✅ landed — reader thread + per-method deadline (20 min heavy ops / 120 s default), stale-response discard by JSON-RPC id, EOF → clear "sidecar exited" error. Removes the permanent-hang failure mode. Full async multiplexing still future work. | `1540f6e` |
| §4 — app-wide React error boundary | ✅ landed — recovery UI with Try-again / Restart | `da1e003` |
| S2 — CSP + asset-scope lockdown | ⏸ still held (by design) — apply `docs/security-hardening.md` checklist on a real build |

New findings from the frontend/Rust deep-read (2026-07-02):

- **F1 (Med, UX):** `Generate.tsx` polls `model.poll_task` every 2 s with **no
  deadline** — a task stuck in PROCESSING spins the progress bar forever. The
  sidecar's `POLL_CAP_S = 300` constant exists but nothing enforces it. Add a
  frontend deadline (~10 min) with a friendly timeout + retry.
- **F2 (Low, perf):** production JS bundle is 1.15 MB in one chunk (three.js
  monolithic import). Code-split the 3D preview (`React.lazy`) to cut first
  paint; low priority for a desktop webview but free wins exist.
- **F3 (Info, build):** `src-tauri/resources/*` (sidecar.exe, addon zip) exist
  only where `build-sidecar.ps1` last ran — `cargo check` fails in a fresh
  clone until it's run once. Document in README or make the build script the
  single entry point.
- Otherwise the deep-read **confirmed** the original assessment: screens
  handle unmount races correctly (`cancelled` flags), IPC error paths set
  user-visible state, no XSS sinks, no unhandled-rejection patterns found.

**Method / honesty note:** The Python sidecar (dispatcher, every code-generating op, orchestrator, network clients, model downloader, project I/O, settings, slicer) and the Rust/Tauri shell (sidecar spawning, IPC, config, capabilities) were **deep-read**. The React/TS frontend was **assessed structurally** (routing, IPC wrapper, error handling, state providers, plus a `dangerouslySetInnerHTML`/`eval` sink grep) — individual screen UX was not line-audited. Product/roadmap context is drawn from the repo's own docs (HANDOFF, ISSUES, pipeline).

---

## Verdict

Conjure3D is a **well-engineered late-prototype**, not yet a commercial product. The code quality is genuinely above average for its stage: consistent safe-templating discipline in the Blender code-gen path, secrets in the OS credential store, `argv`-not-shell subprocess calls, structured error codes, Pydantic `extra='forbid'` on LLM output, atomic file writes, and unusually good rationale docstrings. There is a real test culture (~30 backend unit-test files).

What stands between it and "launch to thousands" is **not** a pile of bugs — it's four structural realities:

1. The product's core depends on an **external Blender install driven through a third-party addon that the code itself documents as unstable** ("silently dies after the first heavy op").
2. That addon exposes an **unauthenticated arbitrary-code-execution socket** on localhost as a *required* part of normal operation.
3. There is **no code-signing and no update channel** — fatal for install conversion and for shipping security patches.
4. **Onboarding requires the user to hand-assemble a toolchain** (Blender + addon + Bambu Studio + bring-your-own API keys) before the app does anything.

These outrank every code-level nit below. A launch plan should sequence around them.

---

## 1. Top launch blockers (highest impact first)

### 1.1 — Dependence on external Blender + an unstable third-party addon `[ARCHITECTURE / RELIABILITY]`
`sidecar/blender_client.py:24-44` documents the core fragility: the BlenderMCP addon's daemon thread "silently goes dark mid-session," and the entire persistent-session design (`session_scope`, 5-retry backoff) exists to work *around* a dependency you don't control. For a mass-market app this is the single biggest reliability risk: every generation/edit depends on (a) the user having installed the correct Blender version, (b) the addon being installed and its socket server running, and (c) that third-party server thread not dying.
**Direction:** own this layer. Options, roughly in order of effort/robustness: pin and **bundle a known-good Blender** (portable/headless) + a **hardened fork of the addon** you control; or replace the addon with a first-party Blender-Python entry point you ship; or long-term, move the deterministic mesh ops (scale/remesh/normalize/decimate/bisect) off Blender entirely onto an embeddable library so Blender is only needed for the exotic cases. At minimum, add a supervisor that detects the dead-thread condition and auto-restarts the addon server.

### 1.2 — Unauthenticated local RCE socket (127.0.0.1:9876) `[SECURITY]`
Normal operation requires an **open TCP socket that executes arbitrary Python** sent to it (`execute_code`). It's unauthenticated: any local process on the machine can connect while Blender is up and run code with the user's privileges (file access, network, etc.). This is inherent to the upstream addon, but shipping it as a *required* runtime posture is a real commercial-security liability.
**Direction:** as part of owning the addon (1.1), add a per-session shared-secret handshake, bind tightly to loopback, and consider a random port negotiated over the sidecar rather than a fixed well-known one. Document the residual risk.

### 1.3 — No code-signing, no auto-updater `[GROWTH / SECURITY]`
`tauri.conf.json` bundles an unsigned NSIS installer (`bundle.targets: "nsis"`, no `windows.certificateThumbprint`) and configures **no updater**. Unsigned → Windows SmartScreen "Unknown Publisher" on every install, which measurably tanks conversion. No updater → no way to push the security/bug fixes this list implies once users are in the wild.
**Direction:** acquire an EV (or OV) code-signing cert and wire signing into the bundle; add the Tauri updater with a signed release feed before any public release.

### 1.4 — Onboarding friction `[PRODUCT / UX]`
Today the wizard makes the user install Blender, install the addon, verify a socket, install Bambu Studio, and paste a Meshy (or Tripo) API key before first value. For a consumer/creator audience that's a steep cliff; each step is a drop-off point.
**Direction:** collapse the toolchain — bundle Blender+addon (1.1) so those wizard steps vanish; offer a **hosted generation option** (see 1.5) so there's no BYO-key wall for the default path; make Bambu optional/deferred until the user actually exports.

### 1.5 — Cost model: who pays for generation? `[PRODUCT / BUSINESS]`
`sidecar/meshy.py` spends real Meshy credits per call, keyed to the user's own API key. That's a developer-preview posture, not a product. At scale you need a decision: pass-through BYO-key (niche/pro), or a hosted proxy with your own account + metering/quotas/billing (consumer). This choice drives auth, backend infrastructure, and pricing — it's a prerequisite for "millions of users," not a detail.

---

## 2. Security findings

Overall the code is **security-conscious**; the Blender code-gen path — the scariest surface — is uniformly safe (every value is `json.dumps`/`repr`-templated or whitelisted; numeric params are type-checked first; ops validate again; no `eval`/`exec` on untrusted data; LLM output passes a Pydantic `extra='forbid'` gate). Findings below are the residue, ordered by severity.

| # | Sev | Location | Issue | Fix |
|---|-----|----------|-------|-----|
| S1 | Med | `sidecar/main.py:100-103` | `system.open_url` calls `webbrowser.open(params["url"])` with **no scheme validation** — a non-http(s) URL (`file://`, other handlers) could be opened. Reachable from the webview via the generic passthrough. | Whitelist `http`/`https` (and reject everything else) before opening. *Safe to patch now.* |
| S2 | Med (defense-in-depth) | `tauri.conf.json:22-28` | `"csp": null` **and** `assetProtocol.scope: ["**"]` (webview may load any file on disk). No active XSS sink exists today (frontend grep: no `dangerouslySetInnerHTML`/`innerHTML`/`eval`; React auto-escapes), so this is latent — but combined with the generic sidecar passthrough (§3.1), *any* future XSS becomes full sidecar access + arbitrary local file read. | Set a locked-down CSP; narrow `assetProtocol.scope` to the projects dir. **Needs testing** — a CSP can break three.js/WASM/asset loads, and narrowing the asset scope can break the GLB preview. Do under test, not blind. |
| S3 | Med | `sidecar/llm_model_download.py:47-50, 275-293` | The 4.4 GB GGUF is fetched over HTTPS with **no pinned checksum** by default (`expected_sha256` is optional and the dispatcher only passes one if the caller supplies it). A compromised/MITM'd mirror could deliver a swapped model. | Pin the real published SHA-256 as a constant and pass it on the default download path. (Needs the actual hash — can't be invented.) |
| S4 | Low | `sidecar/addon.py:62-63` | `zipfile.extractall()` (classic zip-slip) — but on a **first-party bundled** zip, not user input, so not currently exploitable. | Add member-path validation before extract as defense-in-depth (cheap; guards against a tampered resource). |
| S5 | Low | `sidecar/project.py:194` | `edits` loaded from a `.conjure3d.json` are returned to the UI and later re-run through `edit.apply_chain` **without** re-validation through the Pydantic schema. The orchestrator's `float()/int()` coercion + per-op whitelists prevent code injection, so this is robustness, not RCE. | Re-validate loaded chains through `validate_chain` on load; reject/relabel unknown ops. |
| S6 | Info | `meshy.py`, `llm_openrouter.py`, etc. | API error **bodies** are surfaced verbatim to the UI/logs. Bodies don't carry the key (it's a request header), so this is acceptable; just ensure logs are treated as user-shareable (the Copy-diagnostic feature already exposes them). | Keep; note in privacy policy. |

**Done right (keep):** API keys in Windows Credential Manager, never logged (`meshy.py:48-59`, `llm_openrouter.py:250-256`); Tauri capabilities minimized to `core:default` (`capabilities/default.json`) so the webview can't reach fs/shell/http plugins directly; subprocess via `argv` list, never a shell string (`slicer.rs`/`sidecar.rs:57`, `slicer.py:44-52`); settings file carries **no** secrets.

---

## 3. Architecture & scalability

### 3.1 — Single-process, serialized IPC with no timeout `[PRINCIPAL-ENG]`
`src-tauri/src/sidecar.rs:109-136,178-188`: all IPC funnels through one `Mutex<SidecarState>` and a blocking `read_line` on a single stdio pipe, one request/response at a time. Implications:
- **Head-of-line blocking:** a long `edit.apply_chain` (Blender chain, up to minutes) holds the mutex, so every other call — status polls, diagnostics — **queues behind it**. (Note: Tauri commands run off the UI thread, so React keeps painting; what stalls is concurrent IPC, not the render loop.)
- **No read timeout / watchdog:** if a Blender op wedges, the Rust `read_line` blocks **indefinitely**, holding the mutex; the app's IPC is then permanently stuck until the process is killed. There's no supervision or restart of the sidecar.
- **Generic passthrough:** `invoke_sidecar(method, params)` forwards *any* method verbatim — convenient, but it means the whole sidecar command surface is one XSS away (ties to S2).
**Direction:** move to an async, correlation-id-multiplexed channel (or a request queue with per-call timeouts + cancellation); add a sidecar supervisor that health-checks and restarts; consider narrowing the passthrough to an allowlist of known methods.

### 3.2 — Sidecar as a single point of failure
One PyInstaller `--onefile` sidecar process owns generation, editing, LLM, downloads, and Bambu handoff. `--onefile` also has a cold-start cost (self-extract) on every launch. No crash-restart. For reliability at scale, add supervision + a fast-path health check, and consider `--onedir` to cut startup latency.

### 3.3 — Cancellation is uneven
The model download supports cancel; the **Blender edit chain does not** — once `apply_chain` starts, the user can't abort a slow remesh. Long-running, user-triggered work should be cancellable.

---

## 4. Quality / QA

**Strengths:** ~30 backend unit-test files with real acceptance assertions (volume-preservation, manifold checks, dimension tolerances); frontend unit tests for the pure logic (slugify, edits, project, diagnostic, connection). This is a solid base.

**Gaps for launch:**
- **No end-to-end test across the Tauri boundary.** The webview→Rust→sidecar→Blender path is only exercised piecewise. A headless smoke test of the full generate→edit→export flow would catch integration regressions the unit tests can't.
- **"Live" tests require Blender running** (manual acceptance, `manual-blender-tests.md`) — so the highest-value paths aren't in CI. Consider a CI runner with headless Blender.
- **No top-level React error boundary** (`src/App.tsx:130-141`): a render-throw in any screen white-screens the app with no recovery. There's a local `GltfErrorBoundary` in the 3D preview but nothing app-wide.
- **No crash telemetry / opt-in analytics.** At scale you're blind to field failures. Add opt-in error reporting (respecting the local-first privacy posture) so you learn what breaks on real machines.

---

## 5. Product, UX & growth

### Onboarding (biggest UX lever) — see 1.4
Bundle the toolchain so the wizard drops from 5 gates to ~1. Offer a "just try it" hosted path with no key wall. Defer Bambu setup until first export. Add a sample project / one-click demo so first-run shows value before any setup.

### Resilience UX
Surface the addon-connection health prominently (the `ConnectionBadge` exists — good) and make recovery one click ("Reconnect Blender"). Given 1.1, users *will* hit the dead-socket state; the app should self-heal or guide, not dead-end.

### Feature roadmap (marketability)
- **Print-success features:** auto-orientation for printability, support/overhang preview, hollowing + drain holes, wall-thickness/min-feature checks *before* the user wastes filament. These are the difference between "makes a mesh" and "makes a *printable* mesh" and are strong differentiators.
- **Multi-slicer / multi-printer:** today it's Bambu-only. PrusaSlicer/OrcaSlicer/Cura export widens the market a lot for near-zero product risk.
- **Model library / re-editability:** projects persist (`.conjure3d.json`) — build a gallery, versioning, and re-open-to-edit. Encourages retention.
- **Generation depth:** iterate/refine loops, reference-image input, style presets, and a curated prompt gallery lower the "blank prompt" barrier.
- **Sharing / community:** export-to-share, a public gallery, or printables-style publishing — organic growth loops.

### Platform reach
Windows-only (`nsis`) caps the market. macOS/Linux Tauri targets are incremental once the Blender-bundling story (1.1) is solved.

---

## 6. Recommended roadmap

**Now (launch-blocking):**
- Own the Blender layer: bundle Blender + hardened addon; add socket auth + supervisor/auto-restart (1.1, 1.2, 3.1 watchdog).
- Code-signing + auto-updater (1.3).
- Decide the cost model (1.5) — it gates backend/auth work.
- Patch S1 now; schedule S2/S3/S4/S5 under test.
- Top-level error boundary + opt-in crash telemetry (§4).

**Next (quality + conversion):**
- Async multiplexed IPC with timeouts + cancellation (3.1, 3.3).
- E2E test with headless Blender in CI (§4).
- Onboarding redesign + hosted "try it" path (1.4).
- Printability features (auto-orient, wall-thickness, hollowing) (§5).

**Later (expansion):**
- Multi-slicer export; macOS/Linux; model library/community; generation refinement loops.

---

## 7. What I can start on now

- **A — Apply the safe security patches under test** (S1 open_url whitelist now; S4 zip-slip guard; S5 loaded-chain re-validation; scaffold S2 CSP/asset-scope behind a test so it's verifiable before enabling).
- **B — Harden the IPC layer** (add a Rust-side read timeout + sidecar health-check/restart; the lowest-effort slice of 3.1 that removes the permanent-hang failure mode).
- **C — Resilience for the Blender addon** (auto-detect the dead-socket state and reconnect/restart, with clear UX) — the highest reliability ROI.
- **D — A concrete design doc** for one big-ticket item (bundled-Blender packaging, or the hosted-generation + cost model) before any code.
