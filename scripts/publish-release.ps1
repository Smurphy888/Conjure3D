<#
.SYNOPSIS
  Publish a Conjure3D release to the PUBLIC releases-only repo
  (Smurphy888/conjure3d-releases), never the private source repo.

.DESCRIPTION
  LAUNCH_AUDIT 1.3 / two-repo split: source stays private in
  Smurphy888/conjure3d; only compiled artifacts (installer, .sig,
  latest.json) go to the public repo so the updater's unauthenticated
  GET against GitHub Releases works without exposing source.

  Reads the built installer + .sig from
  src-tauri/target/release/bundle/nsis/ (run pnpm tauri build with
  TAURI_SIGNING_PRIVATE_KEY set FIRST — this script does not build).

  Auth: a fine-grained GitHub PAT with **Contents: read and write**
  scoped to ONLY the conjure3d-releases repo, passed via the
  GITHUB_RELEASE_TOKEN environment variable. Never hardcode it here,
  never commit it, never print it.

.PARAMETER Version
  Release version, e.g. "0.1.0". Must match tauri.conf.json/package.json.

.PARAMETER Notes
  Release notes shown in latest.json / the GitHub Release body.

.EXAMPLE
  $env:GITHUB_RELEASE_TOKEN = "github_pat_..."
  .\scripts\publish-release.ps1 -Version "0.1.0" -Notes "First public build"
#>
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][string]$Notes
)

$ErrorActionPreference = "Stop"

if (-not $env:GITHUB_RELEASE_TOKEN) {
    Write-Error "GITHUB_RELEASE_TOKEN is not set. Create a fine-grained PAT scoped to ONLY Smurphy888/conjure3d-releases (Contents: read/write) and set it before running this script."
    exit 1
}

$RepoOwner = "Smurphy888"
$RepoName  = "conjure3d-releases"
$RepoRoot  = Split-Path -Parent $PSScriptRoot
$BundleDir = Join-Path $RepoRoot "src-tauri\target\release\bundle\nsis"

$InstallerName = "Conjure3D_${Version}_x64-setup.exe"
$InstallerPath = Join-Path $BundleDir $InstallerName
$SigPath       = "$InstallerPath.sig"

if (-not (Test-Path $InstallerPath)) {
    Write-Error "Installer not found: $InstallerPath`nBuild it first: pnpm tauri build (with TAURI_SIGNING_PRIVATE_KEY set)."
    exit 1
}
if (-not (Test-Path $SigPath)) {
    Write-Error "Signature not found: $SigPath`nThe build ran without TAURI_SIGNING_PRIVATE_KEY set — no .sig was produced."
    exit 1
}

$Headers = @{
    Authorization = "Bearer $($env:GITHUB_RELEASE_TOKEN)"
    Accept        = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
}

Write-Output "Creating GitHub Release v$Version on $RepoOwner/$RepoName ..."
$releaseBody = @{
    tag_name = "v$Version"
    name     = "v$Version"
    body     = $Notes
    draft    = $false
} | ConvertTo-Json

$release = Invoke-RestMethod -Method Post `
    -Uri "https://api.github.com/repos/$RepoOwner/$RepoName/releases" `
    -Headers $Headers -Body $releaseBody -ContentType "application/json"

$uploadBase = $release.upload_url -replace '\{.*\}', ''

function Upload-Asset($FilePath, $AssetName, $ContentType) {
    Write-Output "Uploading $AssetName ..."
    $bytes = [System.IO.File]::ReadAllBytes($FilePath)
    Invoke-RestMethod -Method Post `
        -Uri "$uploadBase`?name=$AssetName" `
        -Headers $Headers -Body $bytes -ContentType $ContentType | Out-Null
}

Upload-Asset $InstallerPath $InstallerName "application/octet-stream"
Upload-Asset $SigPath "$InstallerName.sig" "text/plain"

# latest.json — the updater feed. signature field is the RAW CONTENTS of the
# .sig file (already base64-armored by the Tauri signer), not re-encoded.
$sigContent = Get-Content $SigPath -Raw
$latestJson = @{
    version   = $Version
    notes     = $Notes
    pub_date  = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    platforms = @{
        "windows-x86_64" = @{
            signature = $sigContent.Trim()
            url       = "https://github.com/$RepoOwner/$RepoName/releases/download/v$Version/$InstallerName"
        }
    }
} | ConvertTo-Json -Depth 5

$latestJsonPath = Join-Path $env:TEMP "latest.json"
Set-Content -Path $latestJsonPath -Value $latestJson -Encoding utf8NoBOM
Upload-Asset $latestJsonPath "latest.json" "application/json"
Remove-Item $latestJsonPath -Force

Write-Output ""
Write-Output "Published: https://github.com/$RepoOwner/$RepoName/releases/tag/v$Version"
Write-Output "Update feed: https://github.com/$RepoOwner/$RepoName/releases/latest/download/latest.json"
