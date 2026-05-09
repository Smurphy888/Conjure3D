"""
Blender addon installation: extracts the bundled blender_mcp_addon.zip into the
user's Blender scripts/addons directory for the detected Blender version.
"""
import os
import sys
import zipfile
from pathlib import Path


def _resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        # Running as PyInstaller exe: bundled resources sit next to the exe
        return Path(sys.executable).parent
    # Development: resources are in src-tauri/resources/ (same layout as the bundle)
    return Path(__file__).parent.parent / "src-tauri" / "resources"


def _major_minor(version: str) -> str:
    """Return 'X.Y' from any 'X.Y' or 'X.Y.Z' version string."""
    parts = version.split(".")
    if len(parts) < 2:
        raise ValueError(f"Version must have at least major.minor: {version!r}")
    return f"{parts[0]}.{parts[1]}"


def install_addon(
    blender_version: str,
    zip_path: Path | None = None,
    addons_root: Path | None = None,
) -> dict:
    """
    Extract blender_mcp_addon.zip into the Blender addons directory.

    Args:
        blender_version: Blender version string e.g. "4.2.3" or "4.3"
        zip_path: Override location of addon zip (for testing)
        addons_root: Override root of Blender's per-version dirs (for testing)

    Returns:
        {"ok": True, "path": str} on success
        {"ok": False, "error": str} on failure
    """
    try:
        major_minor = _major_minor(blender_version)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    if zip_path is None:
        zip_path = _resource_dir() / "blender_mcp_addon.zip"

    if not zip_path.exists():
        return {"ok": False, "error": f"Addon zip not found: {zip_path}"}

    if addons_root is None:
        appdata = os.environ.get("APPDATA", "")
        addons_root = Path(appdata) / "Blender Foundation" / "Blender"

    addons_dir = addons_root / major_minor / "scripts" / "addons"
    try:
        addons_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(addons_dir)
        return {"ok": True, "path": str(addons_dir)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
