# Release signing & auto-update

Implements LAUNCH_AUDIT.md §1.3. Two independent signing systems are involved
— don't confuse them:

| | Purpose | Key | Status |
|---|---|---|---|
| **Updater signing** | The auto-updater verifies each update artifact against a pinned minisign pubkey before installing | `%USERPROFILE%\.tauri\conjure3d_updater.key` (+ `.pub`) | ✅ generated, pubkey pinned in `tauri.conf.json` |
| **Windows code-signing** | SmartScreen / "Unknown Publisher" on the installer itself | OV/EV certificate or Azure Trusted Signing | ⏳ requires purchase — see below |

## Updater — how it works now

- `tauri.conf.json` → `bundle.createUpdaterArtifacts: true` makes every
  `pnpm tauri build` also emit `*-setup.exe.sig` (signed with the private key)
  alongside the NSIS installer.
- `plugins.updater.pubkey` pins the public half; the app refuses any update
  whose signature doesn't verify. Losing the private key means users on old
  versions can never auto-update again — **back it up** (password manager /
  offline copy).
- The frontend `UpdateChip` checks the endpoint ~5 s after startup; failures
  (offline, endpoint not live) are silent by design.

### Building a release

```powershell
# from the worktree (node_modules + venv live there)
# NOTE: the bundler wants the key CONTENTS in TAURI_SIGNING_PRIVATE_KEY —
# the _PATH variant is not honoured by every CLI version.
$env:TAURI_SIGNING_PRIVATE_KEY = Get-Content "$env:USERPROFILE\.tauri\conjure3d_updater.key" -Raw
.\scripts\build-sidecar.ps1
pnpm tauri build
```

Without `TAURI_SIGNING_PRIVATE_KEY` set, the build fails at the signing step
once `createUpdaterArtifacts` is on (installer is still produced; only the
`.sig` step aborts).

### Publishing a release

The endpoint currently configured is a **placeholder** (no git remote exists
yet): `https://github.com/conjure3d/conjure3d/releases/latest/download/latest.json`.
When a GitHub repo exists, update the org/name in `tauri.conf.json` and attach
to each GitHub Release:

1. `Conjure3D_<ver>_x64-setup.exe`
2. `Conjure3D_<ver>_x64-setup.exe.sig`
3. `latest.json`:

```json
{
  "version": "0.1.0",
  "notes": "What changed",
  "pub_date": "2026-07-02T00:00:00Z",
  "platforms": {
    "windows-x86_64": {
      "signature": "<contents of the .exe.sig file>",
      "url": "https://github.com/<org>/<repo>/releases/download/v0.1.0/Conjure3D_0.1.0_x64-setup.exe"
    }
  }
}
```

The `version` field must be greater than the installed app's version for the
chip to appear. Bump `version` in `tauri.conf.json` + `package.json` +
`src-tauri/Cargo.toml` together per release.

## Windows code-signing — decision needed

Unsigned installers trigger SmartScreen's "Windows protected your PC" screen,
which kills install conversion for a consumer product. Options:

| Option | Cost | Notes |
|---|---|---|
| **Azure Trusted Signing** | ~$9.99/mo | Cheapest path; needs an Azure account + identity validation (3+ yr old orgs or individual). Integrates via `signtool` dlib — set `bundle.windows.signCommand`. Recommended first step. |
| **OV certificate** (Sectigo/DigiCert/SSL.com) | ~$80–250/yr | SmartScreen reputation builds over time/volume — warnings continue until enough installs accumulate. |
| **EV certificate** | ~$250–700/yr | Immediate SmartScreen reputation. Requires hardware token or cloud HSM; registered business entity. |

Once a certificate exists, fill `bundle.windows.certificateThumbprint` (cert
in the machine store) or switch to `signCommand` for Trusted Signing — the
scaffold (digest algorithm, timestamp URL) is already in `tauri.conf.json`.

**Order of operations for launch:** signing cert → publish repo/releases →
flip the updater endpoint → every subsequent release reaches installed users
automatically.
