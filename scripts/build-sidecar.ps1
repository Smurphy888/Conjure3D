# Build the thin Python sidecar into a standalone sidecar.exe via PyInstaller.
# Run from the repo root: .\scripts\build-sidecar.ps1
# Output: src-tauri\resources\sidecar.exe

Set-StrictMode -Version Latest
# NOTE: do NOT set $ErrorActionPreference = "Stop" globally. PyInstaller writes
# its INFO progress log to stderr; under Windows PowerShell that surfaces as a
# NativeCommandError and "Stop" would abort the build mid-run (the .exe then
# bundled by `cargo tauri build` is stale -> "Method not found" at runtime).
# We detect real failure via $LASTEXITCODE instead.
$ErrorActionPreference = "Continue"

$repoRoot = Split-Path $PSScriptRoot -Parent
$sidecarDir = Join-Path $repoRoot "sidecar"
$resourcesDir = Join-Path $repoRoot "src-tauri\resources"

Write-Host "Building sidecar.exe with PyInstaller..."

Push-Location $sidecarDir
try {
    # 2>&1 merges stderr into the stream so PS does not treat INFO logs as errors.
    # --add-data bundles the sample GLB fixtures so meshy_mock works in the
    # installed exe (Phase F deferred -> mock is the default; without this the
    # mock returns paths to fixtures that don't exist inside the onefile bundle
    # and the preview screen errors). Windows PyInstaller uses SRC;DEST.
    # SRC must be ABSOLUTE: with --specpath build, PyInstaller resolves a
    # relative --add-data source against the specpath (build/), not cwd.
    $fixturesSrc = Join-Path $sidecarDir "tests\fixtures"
    # Phase J.1: also bundle the LLM grammar. llm.py loads it at runtime via
    # sys._MEIPASS when frozen; without --add-data the grammar disappears
    # from the bundle and constrained sampling falls back to free-form (a
    # quiet, dangerous degradation rather than a loud failure).
    $grammarSrc = Join-Path $sidecarDir "llm_grammar.gbnf"
    python -m PyInstaller `
        --onefile `
        --name sidecar `
        --distpath dist `
        --workpath build `
        --specpath build `
        --hidden-import=keyring.backends.Windows `
        --add-data "$fixturesSrc;tests/fixtures" `
        --add-data "$grammarSrc;." `
        --noconfirm `
        main.py 2>&1 | Write-Host
    $pyrc = $LASTEXITCODE
} finally {
    Pop-Location
}

if ($pyrc -ne 0) {
    Write-Error "PyInstaller failed with exit code $pyrc"
    exit 1
}

$exePath = Join-Path $sidecarDir "dist\sidecar.exe"
if (-not (Test-Path $exePath)) {
    Write-Error "Build failed: dist\sidecar.exe not found"
    exit 1
}

if (-not (Test-Path $resourcesDir)) {
    New-Item -ItemType Directory -Path $resourcesDir | Out-Null
}

Copy-Item -Path $exePath -Destination (Join-Path $resourcesDir "sidecar.exe") -Force

$size = (Get-Item (Join-Path $resourcesDir "sidecar.exe")).Length / 1MB
Write-Host "sidecar.exe copied to src-tauri\resources\ ($([math]::Round($size, 1)) MB)"

# Also stage the BlenderMCP addon zip so the installer always has the latest
# vendored copy. The canonical source is sidecar\resources\; the Tauri bundle
# pulls from src-tauri\resources\. Without this step, edits to the vendored
# addon silently never reached the installer until someone manually ran
# scripts\package-addon.ps1 — which is the exact class of bit-rot bug we just
# spent the day debugging.
& (Join-Path $PSScriptRoot "package-addon.ps1")
if ($LASTEXITCODE -ne 0) {
    Write-Error "package-addon.ps1 failed"
    exit 1
}
