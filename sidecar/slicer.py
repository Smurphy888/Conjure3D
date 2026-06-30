"""
slicer.launch — hand the finished STLs off to Bambu Studio (ISSUES.md #25 /
pipeline.md § Phase 8).

Strict contract per ISSUES.md #25: the Bambu Studio executable path is read
**only** from settings (``bambu_path``, set by the wizard). There is no
auto-detect fallback here — if it is unset the call returns the
``BAMBU_PATH_MISSING`` error code so the frontend can route the user to
Settings (which can itself run ``bambu.detect_bambu`` to pre-fill). This keeps
the wizard's verification step meaningful.

launch() never raises across the JSON-RPC boundary for an expected condition
(missing path / missing files): it returns ``{"ok": False, "error_code": ...}``
with one of ``ERROR_CODES`` so the frontend branches on a stable string, not a
parsed message.

Spawn is fire-and-forget: Bambu is started detached (Windows
``DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP``) so closing/restarting the
sidecar does not kill it. The returned ``pid`` is a launch-time snapshot, not
a liveness signal. The exe + STL paths are passed as an argv **list**, never a
shell string, so an apostrophe/space in any path is safe.
"""
import os
import subprocess
from pathlib import Path

from settings import read_settings

# Single source of truth for the frontend's branch logic. Tests pin these
# exact strings; renaming one is a frontend-breaking change.
ERROR_CODES = (
    "BAMBU_PATH_MISSING",   # settings.bambu_path is null/empty (run wizard)
    "BAMBU_PATH_INVALID",   # configured path does not exist on disk
    "NO_STL_FILES",         # caller passed no stl_paths
    "STL_FILES_MISSING",    # one or more listed STLs not on disk
)


def _err(code: str, message: str, **extra) -> dict:
    assert code in ERROR_CODES, f"undeclared error code {code!r}"
    return {"ok": False, "error_code": code, "message": message, **extra}


def _spawn(exe: str, stl_paths: list) -> int:
    """Start Bambu detached and return its launch-time pid. argv list only."""
    kwargs: dict = {"close_fds": True}
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    proc = subprocess.Popen([exe, *stl_paths], **kwargs)
    return proc.pid


def launch(params: dict) -> dict:
    """
    params: {"stl_paths": [str, ...]}

    Returns on success::

        {"ok": True, "launched": True, "pid": int,
         "bambu_path": str, "stl_paths": [str, ...]}

    or, for an expected failure, ``{"ok": False, "error_code": <ERROR_CODES>,
    "message": str, ...}``.
    """
    stl_paths = params.get("stl_paths") or []
    # A malformed stl_paths is a caller/programmer bug, not a user-facing
    # condition — surface it as TypeError (→ JSON-RPC internal error), not
    # as one of the structured ERROR_CODES the frontend branches on.
    if not isinstance(stl_paths, list) or not all(
        isinstance(p, str) for p in stl_paths
    ):
        raise TypeError("stl_paths must be a list[str]")

    bambu_path = read_settings().get("bambu_path")
    if not bambu_path:
        return _err(
            "BAMBU_PATH_MISSING",
            "Bambu Studio path is not set. Open Settings to configure it.",
        )
    if not Path(bambu_path).is_file():
        return _err(
            "BAMBU_PATH_INVALID",
            f"Configured Bambu Studio path does not exist: {bambu_path}",
        )

    if not stl_paths:
        return _err("NO_STL_FILES", "No STL files to open.")
    missing = [p for p in stl_paths if not Path(p).is_file()]
    if missing:
        return _err(
            "STL_FILES_MISSING",
            f"STL file(s) not found: {missing}",
            missing=missing,
        )

    pid = _spawn(bambu_path, stl_paths)
    return {
        "ok": True,
        "launched": True,
        "pid": pid,
        "bambu_path": bambu_path,
        "stl_paths": list(stl_paths),
    }
