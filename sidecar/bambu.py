"""
Bambu Studio detection: checks default Program Files paths and PATH.
Returns {found, path} where path is the full exe path or None.
"""
import os
import subprocess
from pathlib import Path


def _candidates() -> list:
    candidates = []

    pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    for folder_rel in ("Bambu Studio", r"BambuLab\Bambu Studio"):
        exe = pf / folder_rel / "bambu-studio.exe"
        if exe.exists():
            candidates.append(exe)

    # Local AppData — some Bambu Studio versions install per-user
    local_app = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    for folder_rel in ("Bambu Studio", r"BambuLab\Bambu Studio"):
        exe = local_app / folder_rel / "bambu-studio.exe"
        if exe.exists():
            candidates.append(exe)

    try:
        r = subprocess.run(
            ["where", "bambu-studio"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        for line in r.stdout.strip().splitlines():
            p = Path(line.strip())
            if p.exists():
                candidates.append(p)
    except Exception:
        pass

    return candidates


def detect_bambu() -> dict:
    for exe in _candidates():
        if exe.exists():
            return {"found": True, "path": str(exe)}
    return {"found": False, "path": None}
