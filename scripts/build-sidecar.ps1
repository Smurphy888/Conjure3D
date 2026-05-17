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
    python -m PyInstaller `
        --onefile `
        --name sidecar `
        --distpath dist `
        --workpath build `
        --specpath build `
        --hidden-import=keyring.backends.Windows `
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
