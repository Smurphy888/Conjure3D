# Build the thin Python sidecar into a standalone sidecar.exe via PyInstaller.
# Run from the repo root: .\scripts\build-sidecar.ps1
# Output: src-tauri\resources\sidecar.exe

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path $PSScriptRoot -Parent
$sidecarDir = Join-Path $repoRoot "sidecar"
$resourcesDir = Join-Path $repoRoot "src-tauri\resources"

Write-Host "Building sidecar.exe with PyInstaller..."

Push-Location $sidecarDir
try {
    # When keyring usage lands, add: --hidden-import=keyring.backends.Windows
    python -m PyInstaller `
        --onefile `
        --name sidecar `
        --distpath dist `
        --workpath build `
        --specpath build `
        --noconfirm `
        main.py
} finally {
    Pop-Location
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
