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
  src-tauri/target/release/bundle/nsis/ (build + sign FIRST - this
  script does not build; see docs/release-signing.md).

  ATOMIC PUBLISH: the release is created as a DRAFT, all three assets are
  uploaded, and only then is it flipped to published. A failure at any
  point before the final step leaves an invisible draft - the updater
  endpoint (releases/latest/...) never sees a half-populated release.

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

# Windows PowerShell 5.1 can default to TLS 1.0/1.1, which api.github.com
# rejects ("Could not create SSL/TLS secure channel"). Force 1.2.
[Net.ServicePointManager]::SecurityProtocol = `
    [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

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
    Write-Error "Installer not found: $InstallerPath`nBuild it first (see docs/release-signing.md)."
    exit 1
}
if (-not (Test-Path $SigPath)) {
    Write-Error "Signature not found: $SigPath`nThe build ran without signing - no .sig was produced. See docs/release-signing.md."
    exit 1
}

$ApiRoot = "https://api.github.com/repos/$RepoOwner/$RepoName"
$Headers = @{
    Authorization          = "Bearer $($env:GITHUB_RELEASE_TOKEN)"
    Accept                 = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
}

# Fail early if this tag already has a release (re-run after a full success,
# or a leftover from a partial run). Clearer than a raw 422 mid-flight.
try {
    $existing = Invoke-RestMethod -Method Get -Uri "$ApiRoot/releases/tags/v$Version" -Headers $Headers
    if ($existing) {
        Write-Error "A release for tag v$Version already exists (id $($existing.id)). Delete it on GitHub (and its tag) before re-publishing, or bump the version."
        exit 1
    }
} catch {
    # 404 = no such release yet = the expected happy path. Anything else rethrows.
    if ($_.Exception.Response -and $_.Exception.Response.StatusCode.value__ -ne 404) {
        throw
    }
}

Write-Output "Creating DRAFT release v$Version on $RepoOwner/$RepoName ..."
$releaseBody = @{
    tag_name = "v$Version"
    name     = "v$Version"
    body     = $Notes
    draft    = $true          # stays invisible to the updater until we flip it
    prerelease = $false
} | ConvertTo-Json

$release = Invoke-RestMethod -Method Post -Uri "$ApiRoot/releases" `
    -Headers $Headers -Body $releaseBody -ContentType "application/json"

$uploadBase = $release.upload_url -replace '\{.*\}', ''

function Upload-Asset($FilePath, $AssetName, $ContentType) {
    Write-Output "Uploading $AssetName ..."
    # -InFile streams the file rather than buffering a 33 MB byte[] in memory,
    # and avoids Invoke-RestMethod's binary-body quirks on PS 5.1.
    Invoke-RestMethod -Method Post -Uri "$uploadBase`?name=$AssetName" `
        -Headers $Headers -InFile $FilePath -ContentType $ContentType | Out-Null
}

Upload-Asset $InstallerPath $InstallerName "application/octet-stream"
Upload-Asset $SigPath "$InstallerName.sig" "text/plain"

# latest.json - the updater feed. The signature field is the RAW CONTENTS of
# the .sig file (already base64-armored by the Tauri signer), not re-encoded.
$sigContent = (Get-Content $SigPath -Raw).Trim()
$latestJson = @{
    version   = $Version
    notes     = $Notes
    pub_date  = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    platforms = @{
        "windows-x86_64" = @{
            signature = $sigContent
            url       = "https://github.com/$RepoOwner/$RepoName/releases/download/v$Version/$InstallerName"
        }
    }
} | ConvertTo-Json -Depth 5

# Write with NO BOM. `Set-Content -Encoding utf8NoBOM` throws on Windows
# PowerShell 5.1, and `-Encoding utf8` there emits a BOM that can break strict
# JSON parsers. The .NET writer below is BOM-free and identical across PS
# versions.
$latestJsonPath = Join-Path $env:TEMP "conjure3d-latest.json"
[System.IO.File]::WriteAllText($latestJsonPath, $latestJson, (New-Object System.Text.UTF8Encoding($false)))
Upload-Asset $latestJsonPath "latest.json" "application/json"
Remove-Item $latestJsonPath -Force

# Everything uploaded cleanly - flip the draft to published. This is the ONLY
# moment the release becomes visible to the auto-updater.
Write-Output "All assets uploaded - publishing release ..."
$publishBody = @{ draft = $false } | ConvertTo-Json
Invoke-RestMethod -Method Patch -Uri "$ApiRoot/releases/$($release.id)" `
    -Headers $Headers -Body $publishBody -ContentType "application/json" | Out-Null

Write-Output ""
Write-Output "Published: https://github.com/$RepoOwner/$RepoName/releases/tag/v$Version"
Write-Output "Update feed: https://github.com/$RepoOwner/$RepoName/releases/latest/download/latest.json"
