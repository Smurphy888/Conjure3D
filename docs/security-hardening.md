# Security hardening — CSP & asset-protocol scope (S2)

**Status: PROPOSED, not enabled.** This change must be verified in a real build
before merging — a wrong CSP directive or too-narrow asset scope will white-screen
the app or break the 3D preview, and neither is catchable by the Python test suite.
The other three hardening fixes (S1 open_url guard, S4 zip-slip guard, S5 loaded-chain
validation) are already applied with tests; this one is deliberately held.

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
