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

# Pin the build to sidecar\.venv (Python 3.12), not whatever `python` happens
# to resolve to on PATH. Background: llama-cpp-python ships no PyPI wheels for
# Python 3.14, so a system 3.14 install can't import llama_cpp and PyInstaller
# would happily produce a sidecar.exe whose `llm.backend_info` reports
# `library_unavailable` forever. The venv is the only environment that has
# both the llama-cpp-python wheel (from abetlen's index) and the pinned
# PyInstaller version. Hard-fail if it isn't there — a clear "create the venv"
# message is much friendlier than a silent 3.14 fallback that crashes later.
$venvPython = Join-Path $sidecarDir ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Error @"
sidecar\.venv\Scripts\python.exe not found.

Create the build venv first with Python 3.12 (NOT 3.14 — no llama-cpp-python wheel):
  py -3.12 -m venv sidecar\.venv
  sidecar\.venv\Scripts\python.exe -m pip install -U pip wheel setuptools
  sidecar\.venv\Scripts\python.exe -m pip install requests keyring "pydantic>=2.0" pytest responses pyinstaller
  sidecar\.venv\Scripts\python.exe -m pip install "llama-cpp-python>=0.3.0" --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu --only-binary=:all:
"@
    exit 1
}

# Pre-flight: the build is only useful if llama_cpp imports inside the venv.
# A missing llama_cpp means we'd ship a sidecar.exe that always reports
# library_unavailable — exactly what the Python 3.12 migration was meant to
# eliminate. Catch it before PyInstaller spends 90s producing a dud.
& $venvPython -c "import llama_cpp; import PyInstaller" 2>&1 | Write-Host
if ($LASTEXITCODE -ne 0) {
    Write-Error "Pre-flight failed: llama_cpp or PyInstaller is not importable in the venv. Re-run the install commands shown above."
    exit 1
}

Write-Host "Building sidecar.exe with PyInstaller (venv: $venvPython)..."

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
    # --collect-all llama_cpp = --collect-binaries + --collect-datas +
    # --collect-submodules + --copy-metadata. We need every one of those:
    #   * binaries: llama.dll and the GGUF runtime — without these, the first
    #     `Llama(...)` call dies in ctypes loading.
    #   * datas: the wheel ships an llama_cpp/lib/ folder; PyInstaller
    #     wouldn't include it via module scan alone.
    #   * submodules: llm_llama_cpp.py uses lazy imports inside method
    #     bodies (Phase J.4). PyInstaller's modulegraph scans bytecode but
    #     function-body imports occasionally slip through; --collect-submodules
    #     forces the whole package in.
    #   * metadata: package version / dist-info entries some llama_cpp
    #     code paths read from importlib.metadata.
    # --hidden-import=llama_cpp is belt-and-braces against the lazy-import
    # pattern. Either flag alone has a failure mode that surfaces as
    # `install_status: "library_unavailable"` at runtime — exactly the
    # symptom this whole Python-3.12 migration is meant to eliminate.
    & $venvPython -m PyInstaller `
        --onefile `
        --noconsole `
        --name sidecar `
        --distpath dist `
        --workpath build `
        --specpath build `
        --hidden-import=keyring.backends.Windows `
        --hidden-import=llama_cpp `
        --collect-all llama_cpp `
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
