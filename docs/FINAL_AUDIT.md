# Conjure3D — Final Pre-Release Audit (independent verification)

**Auditor stance:** trust nothing from prior reports. Verify every fix against
current source. Find regressions and anything missed. Evidence-based only.

**Architecture reality check (scopes the checklist):** Conjure3D is a *local
desktop app* — Tauri (Rust) shell + React webview + a local Python sidecar
that talks to a local Blender over a loopback socket, plus outbound calls to
Meshy/Tripo/OpenAI/OpenRouter (user's own keys) and a GitHub release feed.
There is **no first-party server, no database, no user accounts, no JWT/session
layer, no CORS surface we own**. So whole sections of a generic web-app
security checklist (SQL/NoSQL injection, JWT flaws, IDOR, server rate-limiting,
DDoS, server CSRF) are **N/A** and marked as such rather than hand-waved.

---

## CHECKPOINT LOG (resume marker)

- [x] C0: baseline — git surveyed, 411 tests pass / 18 skip (exit 0)
- [x] C1: S1 open_url guard — VERIFIED sound (+4 tests)
- [x] C2: S4 zip-slip guard — VERIFIED sound (+2 tests)
- [x] C3: S5 chain re-validation — VERIFIED sound (+3 tests); UI wiring of
        `edits_valid` still not surfaced (LOW, F-D)
- [x] C4: S3 GGUF SHA pin — VERIFIED sound (+4 tests); hash cross-checked
        byte-for-byte vs the real downloaded file
- [x] C5: IPC timeout / dead-process — re-read in full, VERIFIED sound
        (mutex-serialized, stale-response discard by id, no race)
- [x] C6: React error boundary — VERIFIED; caveat: React boundaries don't
        catch async/event-handler throws (inherent) — screens handle their
        own async via try/catch (spot-checked Generate.tsx)
- [x] C7: addon auth token + watchdog — VERIFIED sound (+ source-marker
        tests prevent mirror drift)
- [x] C8: auto-updater wiring — VERIFIED compiles + builds + endpoint set
- [x] C9: fresh re-audit — found F-A (critical, release script)
- [x] C10: fresh security pass — .3mf XML escaping OK, zero frontend XSS
        sinks (independently grepped), token-gated RCE socket
- [x] C11: supply-chain — pnpm audit: 1 low (react-router) FIXED → clean
- [x] C12: perf — see notes (desktop app; main lever is 1.15 MB bundle, LOW)
- [x] C13: UX/a11y — see notes (F1 poll, S2 CSP, signing)
- [x] C14: final report + release decision — see chat + below

Findings are appended below.

---

## FINDINGS

### F-A — CRITICAL (release-blocking) — FIXED — `scripts/publish-release.ps1`
The release publish script — never actually executed before this audit —
would crash on the user's shell (Windows PowerShell 5.1), and worse, would
crash *after* creating the public release and uploading the installer,
leaving a broken "latest" the auto-updater would serve. Three defects:
1. `Set-Content -Encoding utf8NoBOM` — `utf8NoBOM` is **rejected** on PS 5.1
   (verified: only `UTF8` (with BOM) exists there). Plain `UTF8` emits a BOM
   that can break strict JSON parsers reading `latest.json`.
2. Em-dashes (`—`, U+2014) inside double-quoted strings (L67, L144). PS 5.1
   decodes BOM-less UTF-8 script files as ANSI/Windows-1252, mangling the
   3-byte em-dash into a phantom curly-quote that corrupts string parsing —
   the modern PS AST parser reports 2 hard syntax errors. (Comment-scoped
   em-dashes in `build-sidecar.ps1` are harmless because comments are
   line-scoped; that script runs fine, confirming the mechanism.)
3. Non-atomic publish + no TLS 1.2 pin + in-memory binary upload.

**Fix:** rewrote the script to (a) write `latest.json` BOM-free via
`[System.IO.File]::WriteAllText(..., UTF8Encoding($false))`, (b) be pure
ASCII, (c) force TLS 1.2 (PS 5.1 else negotiates TLS 1.0 → GitHub refuses),
(d) publish atomically: create as **draft** → upload all 3 assets → flip to
published as the final step, so a mid-run failure never exposes a broken
release, (e) stream uploads via `-InFile`, (f) pre-check for an existing tag
with a clear error instead of a raw 422 mid-flight. Verified: parses clean
on PS 5.1, no-BOM JSON round-trips.

**Lesson for the checklist:** a release-critical script that has never been
run is not "done." This one passed code review twice and would have failed
on first use.

### F-B — LOW (supply chain) — FIXED — `package.json`
`react-router` 7.15.0 carried GHSA-84g9-w2xq-vcv6 (CSRF via server-side
PUT/PATCH/DELETE document requests). **Not exploitable here** — Conjure3D is a
client-only `HashRouter` in a desktop webview with no server, data-router
mutations, or SSR. Bumped to 7.18.1 anyway for a clean `pnpm audit`; build
verified green.

### F-C — MEDIUM (deferred, not a live defect) — `src-tauri/tauri.conf.json`
`"csp": null` + `assetProtocol.scope: ["**"]`. **No active XSS sink exists**
(independently grep-verified: no `dangerouslySetInnerHTML`/`innerHTML`/`eval`;
React auto-escapes; the one user string rendered — project name — is escaped).
So this is defense-in-depth, not an exploitable hole. A tested lock-down
proposal already exists in `docs/security-hardening.md`; it is deliberately
NOT enabled blind because a wrong directive white-screens the app or breaks
the GLB preview, and that can't be caught by the Python test suite. **Release
call:** acceptable to ship as-is (Approved-with-minor-risks item); enable via
the documented checklist against a real build in the next iteration.

### F-D — LOW — `sidecar/project.py` + frontend
S5 added `edits_valid`/`edits_validation_error` to the `project.load` result,
but no screen surfaces it yet. A tampered/hand-edited `.conjure3d.json` loads
and (harmlessly — orchestrator coerces types + whitelists ops) re-runs without
a user-visible warning. Robustness only, no RCE. Recommend wiring a small
"this project's edit list looks invalid" banner in a fast-follow.

### F-E — LOW (UX) — `src/screens/Generate.tsx`
The generation poll loop (`while (!cancelled)`, 2 s interval) has no deadline;
a task stuck in PROCESSING spins the progress bar indefinitely. Mitigated by
an always-present **Cancel** button (not a hard hang). Recommend a ~10 min
client deadline with a friendly timeout+retry. Not fixed now to avoid a
frontend rebuild/re-test cycle immediately pre-release — fast-follow.

### NOT DEFECTS — commercial/operational items (not code bugs)
- **Unsigned installer** → SmartScreen "unknown publisher." HIGH impact on
  install conversion / "premium feel," but a business/cost item (needs a
  cert), not a code defect. Scaffold is in place (`docs/release-signing.md`).
- **Updater endpoint has no release yet** → `check()` 404s and is silently
  swallowed by design. Resolves the moment the first release is published.
- **Updater private signing key** lives at `%USERPROFILE%\.tauri\` (outside
  repo, correct). Operational risk: losing it strands all installed users on
  their current version forever. MUST be backed up offline. Documented.

## Perf notes (C12)
Desktop app, single local user — most web-scale concerns are N/A. Real levers:
- Frontend bundle is ~1.15 MB in one chunk (three.js not code-split). LOW —
  it loads from local disk in a webview, not over a network. `React.lazy` on
  the 3D preview would trim first paint; optional.
- Sidecar is `--onefile` (self-extracts each launch → cold-start cost).
  `--onedir` would cut startup latency; a packaging change, not urgent.
- Heavy Blender ops are inherently slow but now bounded by the IPC 20-min
  ceiling + the sidecar's per-op HEAVY_TIMEOUT; no unbounded hang path found.

## Verified-sound (no regression, evidence-backed)
S1, S3, S4, S5 (each with passing unit tests) · IPC timeout/dead-process
(full re-read) · error boundary · addon auth+watchdog (source-marker tests) ·
auto-updater (compiles+builds) · .3mf XML escaping · zero frontend XSS sinks ·
secrets in Windows Credential Manager, never logged · subprocess via argv
lists, never shell strings · 411 tests pass, `cargo check` clean, `pnpm build`
clean, `pnpm audit` clean.

