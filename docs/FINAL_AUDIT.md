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

- [x] C0: baseline — git log surveyed, test suite launched
- [ ] C1: verify S1 open_url guard
- [ ] C2: verify S4 zip-slip guard
- [ ] C3: verify S5 chain re-validation
- [ ] C4: verify S3 GGUF SHA pin
- [ ] C5: verify IPC timeout / dead-process
- [ ] C6: verify React error boundary
- [ ] C7: verify addon auth token + watchdog
- [ ] C8: verify auto-updater wiring
- [ ] C9: fresh full re-audit (bugs/edge/race)
- [ ] C10: fresh security pass
- [ ] C11: dependency/supply-chain audit
- [ ] C12: perf pass
- [ ] C13: UX/a11y pass
- [ ] C14: final report + release decision

Findings are appended below as they are confirmed.

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

