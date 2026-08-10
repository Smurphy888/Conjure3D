# Security hardening — CSP & asset-protocol scope (S2)

**Status: CSP ENABLED 2026-07-16 (live-verified). Asset-scope narrowing NOT
applied — left at `["**"]`.** Split outcome, deliberately:

**CSP — applied and verified.** Replaced `csp: null` with the strict policy
below, plus one widening: `blob:` added to `img-src` and `connect-src` (three.js
GLTFLoader loads embedded GLB textures via `URL.createObjectURL`; Meshy's Refine
flow returns textured GLBs — all 8 existing project GLBs were untextured so the
un-widened policy passed today, but refine would have broken). `blob:` originates
from same-document JS only, so it's not a meaningful loosening. Verified on a live
dev build: app boots, no white screen, sidecar IPC round-trip works (provider
line renders), inline styles render, **zero CSP violations in the dev log**. This
is the real security win — `default-src 'self'` blocks the XSS *vector itself*.

**Asset-scope narrowing — NOT applied (and the original proposal's token was
wrong).** The proposal said `scope: ["$LOCALAPPDATA/Conjure3D/**"]`. Verified
against Tauri 2.11 source (`src/path/mod.rs:216` `from_variable`, `src/scope/fs.rs:184`
`Scope::new` → `path().parse()`): **`$LOCALAPPDATA` is not a valid Tauri scope
variable.** The valid set is `$LOCALDATA / $APPLOCALDATA / $APPDATA / $RESOURCE /
$APPCONFIG`. An unknown token is pushed as a *literal* path component, so
`$LOCALAPPDATA/Conjure3D/**` would match no real path and **silently break every
3D preview** — strictly worse than `["**"]`, and invisible to boot/parse checks.
The correct token is **`$LOCALDATA`** (→ `local_data_dir()` = `%LOCALAPPDATA%` on
Windows), i.e. `scope: ["$LOCALDATA/Conjure3D/**"]`, which matches where
`main.py` writes previews. **Left at `["**"]` for now** because (a) it needs a
live GLB-render test to confirm (couldn't be driven this session without spending
Meshy credits), and (b) with the strict CSP already blocking XSS, the marginal
value of narrowing the scope is low — the audit rated `["**"]` acceptable even
with *no* CSP. To enable later: set `$LOCALDATA/Conjure3D/**`, build, then
generate a model and confirm the preview renders (watch devtools for an
asset-scope refusal), including a **custom Save-As dir** which falls outside the
scope.

Original proposal below for reference. The other three hardening fixes (S1
open_url guard, S4 zip-slip guard, S5 loaded-chain validation) were already
applied with tests.

## Why

`src-tauri/tauri.conf.json` currently ships:

```jsonc
"security": {
  "csp": null,                                  // no Content-Security-Policy
  "assetProtocol": { "enable": true, "scope": ["**"] }  // webview may read ANY file
}
```

There is **no active XSS vector today** — a grep of `src/` finds no
`dangerouslySetInnerHTML`, `innerHTML`, `eval`, or `new Function`, and React
auto-escapes. So this is **defense-in-depth**: `invoke_sidecar(method, params)`
is a generic passthrough (`src-tauri/src/sidecar.rs:178`), so *if* an XSS is ever
introduced, `csp:null` + `scope:["**"]` turns it into full sidecar control plus
arbitrary local-file read. Locking both down caps that blast radius.

## Proposed change

```jsonc
"security": {
  // Start strict; widen only for directives the build actually needs.
  "csp": "default-src 'self'; img-src 'self' asset: data: https:; media-src 'self' asset: blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'wasm-unsafe-eval'; connect-src 'self' ipc: http://ipc.localhost asset: http://asset.localhost",
  "assetProtocol": {
    "enable": true,
    // Only the app's own project/output tree — not the whole filesystem.
    "scope": ["$LOCALAPPDATA/Conjure3D/**"]
  }
}
```

### Directive rationale (verify each against the running app)
- `script-src 'self' 'wasm-unsafe-eval'` — bundled JS is same-origin; `wasm-unsafe-eval`
  covers three.js/GLB decoders (Draco/meshopt) **if** used. Drop it if no WASM loads.
- `style-src 'self' 'unsafe-inline'` — the UI uses inline `style={{…}}` heavily
  (e.g. `CursorGlow` in `App.tsx`); React applies most via CSSOM, but keep
  `'unsafe-inline'` unless every inline style is confirmed removed.
- `img-src`/`media-src … asset: blob: data:` — the 3D preview loads GLBs and
  textures through the asset protocol and object URLs.
- `connect-src 'self' ipc: http://ipc.localhost` — Tauri v2 IPC transport. The
  webview does **not** call Meshy/OpenRouter/OpenAI directly (the sidecar does),
  so those origins are intentionally absent from `connect-src`.
- `assetProtocol.scope` — narrowed to `%LOCALAPPDATA%\Conjure3D\**`, which is where
  `main.py` writes previews/exports. Confirm the projects dir actually resolves
  there for all flows before shipping (custom Save-As dirs may fall outside it —
  if so, the preview of a project saved elsewhere would fail to load).

## Verification checklist (the "test" — run on a real build)

1. `pnpm build && cargo tauri build` (or dev) with the change applied.
2. App loads without a blank screen; DevTools console shows **no CSP violation** errors.
3. Full happy path works: generate → 3D preview renders the GLB → edit chain →
   export → the preview updates. (Confirms asset protocol + WASM decoders + blob URLs.)
4. External links still open (About/docs buttons → `system.open_url`).
5. Model-download chip and connection badge still update (IPC/`connect-src`).
6. Load a project saved to a **custom** directory and confirm its preview still
   renders — if not, the asset scope is too narrow; widen it or copy previews into
   the LOCALAPPDATA tree on load.

Only merge once every step passes. If a directive breaks something, widen that
one directive (never fall back to `csp:null`).
```
