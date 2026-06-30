# Copy the BlenderMCP addon zip from sidecar/resources/ to src-tauri/resources/
# so Tauri bundles it into the installer.
# Run from the repo root: .\scripts\package-addon.ps1

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path $PSScriptRoot -Parent
$src = Join-Path $repoRoot "sidecar\resources\blender_mcp_addon.zip"
$resourcesDir = Join-Path $repoRoot "src-tauri\resources"
$dst = Join-Path $resourcesDir "blender_mcp_addon.zip"

if (-not (Test-Path $src)) {
    Write-Error "Source not found: $src`nDrop blender_mcp_addon.zip into sidecar\resources\ first."
    exit 1
}

if (-not (Test-Path $resourcesDir)) {
    New-Item -ItemType Directory -Path $resourcesDir | Out-Null
}

Copy-Item $src $dst -Force
$size = [math]::Round((Get-Item $dst).Length / 1KB, 1)
Write-Host "blender_mcp_addon.zip copied to src-tauri\resources\ ($size KB)"
