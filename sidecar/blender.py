"""
Blender detection: checks registry, Program Files, and PATH (covers Microsoft Store installs).
"""
import os
import re
import subprocess
from pathlib import Path


def _version_from_exe(exe: Path) -> str | None:
    try:
        r = subprocess.run(
            [str(exe), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        m = re.search(r"Blender\s+(\d+\.\d+(?:\.\d+)?)", r.stdout + r.stderr)
        return m.group(1) if m else None
    except Exception:
        return None


def _candidates() -> list:
    candidates = []

    # 1. Registry (HKLM) — standard installer
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\BlenderFoundation") as key:
            i = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(key, i)
                    with winreg.OpenKey(key, subkey_name) as sk:
                        install_dir, _ = winreg.QueryValueEx(sk, "Install_Dir")
                        candidates.append(Path(install_dir) / "blender.exe")
                    i += 1
                except OSError:
                    break
    except (OSError, ImportError):
        pass

    # 2. Default Program Files path
    pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    bf = pf / "Blender Foundation"
    if bf.exists():
        for d in sorted(bf.iterdir(), reverse=True):
            exe = d / "blender.exe"
            if exe.exists():
                candidates.append(exe)

    # 3. PATH / where — catches Microsoft Store and user-custom installs
    try:
        r = subprocess.run(
            ["where", "blender"], capture_output=True, text=True, timeout=3
        )
        for line in r.stdout.strip().splitlines():
            p = Path(line.strip())
            if p.exists():
                candidates.append(p)
    except Exception:
        pass

    return candidates


def detect_blender() -> dict:
    for exe in _candidates():
        if not exe.exists():
            continue
        version = _version_from_exe(exe)
        if version:
            return {"found": True, "path": str(exe), "version": version}
    return {"found": False, "path": None, "version": None}
