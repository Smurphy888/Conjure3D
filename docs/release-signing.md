# Release signing & auto-update

Implements LAUNCH_AUDIT.md §1.3. Two independent signing systems are involved
— don't confuse them:

## Repo layout — source vs. distribution

Conjure3D is closed-source commercial software. Two separate GitHub repos:

| Repo | Visibility | Contents | Remote |
|---|---|---|---|
| `Smurphy888/conjure3d` | **Private** | Full source (this repo) | `origin` |
| `Smurphy888/conjure3d-releases` | **Public** | ONLY compiled installers, `.sig` files, `latest.json` — never source | not cloned locally; published to via `scripts/publish-release.ps1` |

The updater's `endpoints` fetch is a plain unauthenticated `GET` — it only
works against a **public** repo's releases. Splitting source from
distribution keeps the private repo private while still giving the updater
somewhere to fetch from. Never push source, branches, or the private repo's
git history to `conjure3d-releases` — it should only ever receive Release
assets via the publish script.

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

The endpoint in `tauri.conf.json` points at the public releases repo:
`https://github.com/Smurphy888/conjure3d-releases/releases/latest/download/latest.json`.

Publishing is scripted — `scripts/publish-release.ps1` builds nothing itself,
it only uploads what `pnpm tauri build` already produced:

```powershell
# 1. Create a fine-grained PAT at github.com/settings/tokens, scoped to
#    ONLY Smurphy888/conjure3d-releases, permission "Contents: read/write".
#    Never scope it to the private conjure3d repo.
$env:GITHUB_RELEASE_TOKEN = "github_pat_..."

# 2. Publish — reads the installer + .sig from src-tauri/target/release/bundle/nsis/,
#    creates the GitHub Release, uploads the exe, the .sig, and a generated latest.json.
.\scripts\publish-release.ps1 -Version "0.1.0" -Notes "What changed in this release"
```

The script never touches the private `conjure3d` repo — it only calls the
GitHub REST API against `conjure3d-releases`. The token lives in an
environment variable for the duration of the call only; it is never written
to disk, logged, or committed.

The `version` field must be greater than the installed app's version for the
update chip to appear. Bump `version` in `tauri.conf.json` + `package.json` +
`src-tauri/Cargo.toml` together per release, and pass the same version to
`-Version` above.

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
