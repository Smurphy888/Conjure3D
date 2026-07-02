"""
Phase H Issue #26 — ``<slug>.conjure3d.json`` save / load.

BYTE-IDENTICAL GUARANTEE: ``save`` copies ``preview.glb`` + every STL into
the sibling ``<slug>.conjure3d/`` folder. *Those copies* are the
byte-identical record. ``load`` restores Editor state from the JSON and
points at the copied artifacts. Re-running ``edit.apply_chain`` on load is a
separate user affordance for further editing — it is NOT the byte-identical
mechanism (the Blender edit chain is not bit-deterministic: float ordering,
mesh export order, occasional timestamp injection). Do not "fix" this by
trying to make the chain deterministic.

``dst_dir`` / ``project_file`` are explicit params (the frontend computes
them, e.g. from a Save-As dialog). There is no implicit projects-dir
convention in the codebase yet; this module deliberately does not invent one.

An empty ``stl_paths`` is a valid pre-export state, not an error — only the
slicer cares about STL presence. A missing/moved artifact on load is
informational (``ARTIFACT_MISSING`` warning), never fatal.

Paths may contain apostrophes/spaces (the build tree itself does) — always
``pathlib.Path`` + ``shutil``, never shell strings; ``json.dump`` escapes
templated paths.
"""
import json
import shutil
from pathlib import Path

from orchestrator import PROJECT_SCHEMA_VERSION, REQUIRED_PROJECT_FIELDS
from edit_chain_schema import validate_chain
from slugify import slugify

# Frozen contract the frontend branches on (same precedent as
# slicer.ERROR_CODES). ARTIFACT_MISSING is a non-fatal warning code.
ERROR_CODES = (
    "SCHEMA_VERSION_MISMATCH",  # file version != PROJECT_SCHEMA_VERSION
    "PROJECT_FILE_INVALID",     # JSON parse error / missing required fields
    "ARTIFACT_MISSING",         # sibling folder or files moved (warn only)
)

# save() input must carry everything except `version` (save stamps that).
_SAVE_REQUIRED = tuple(f for f in REQUIRED_PROJECT_FIELDS if f != "version")


def _err(code: str, message: str, **extra) -> dict:
    assert code in ERROR_CODES, f"undeclared error code {code!r}"
    return {"ok": False, "error_code": code, "message": message, **extra}


def _artifact_dir(project_file: Path, slug: str) -> Path:
    return project_file.parent / f"{slug}.conjure3d"


def save(params: dict) -> dict:
    """
    params::

        {"dst_dir": str,
         "project": {"name", "prompt", "preview_task_id", "source_glb",
                     "edits": [Edit], "color_split_mode": str,
                     "last_sanity"?: Sanity},
         "artifacts": {"preview_glb": str|None, "stl_paths": [str, ...]}}

    Writes ``<dst_dir>/<slug>.conjure3d.json`` and copies the artifacts into
    the sibling ``<dst_dir>/<slug>.conjure3d/`` folder.

    Callers are responsible for unique artifact basenames: copies are keyed
    by ``Path(src).name``, so two sources sharing a basename silently
    overwrite. The Phase-G producer (``export_stl``) already emits unique
    ``<stem>_<color>.stl`` names, so the happy path never collides.
    """
    dst_dir = params.get("dst_dir")
    project = params.get("project") or {}
    artifacts = params.get("artifacts") or {}
    if not isinstance(dst_dir, str) or not dst_dir:
        raise TypeError("dst_dir must be a non-empty str")
    if not isinstance(project, dict):
        raise TypeError("project must be a dict")

    missing = [f for f in _SAVE_REQUIRED if f not in project]
    if missing:
        return _err(
            "PROJECT_FILE_INVALID",
            f"project is missing required field(s): {missing}",
            missing=missing,
        )

    slug = slugify(str(project["name"]))
    out_dir = Path(dst_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    project_file = out_dir / f"{slug}.conjure3d.json"
    art_dir = _artifact_dir(project_file, slug)
    art_dir.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []

    def _copy_in(src: str | None) -> str | None:
        if not src:
            return None
        s = Path(src)
        if not s.is_file():
            return None
        dest = art_dir / s.name
        shutil.copy2(s, dest)
        copied.append(dest.name)
        return dest.name

    preview_rel = _copy_in(artifacts.get("preview_glb"))
    stl_rels = [r for r in (_copy_in(p) for p in (artifacts.get("stl_paths") or [])) if r]

    doc = {
        "version": PROJECT_SCHEMA_VERSION,
        "name": str(project["name"]),
        "prompt": str(project["prompt"]),
        "preview_task_id": project["preview_task_id"],
        "source_glb": project["source_glb"],
        "edits": list(project.get("edits") or []),
        "color_split_mode": str(project.get("color_split_mode") or "none"),
        "last_sanity": project.get("last_sanity"),
        "artifacts": {"preview_glb": preview_rel, "stl_paths": stl_rels},
    }
    with project_file.open("w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)

    return {
        "ok": True,
        "project_file": str(project_file),
        "artifact_dir": str(art_dir),
        "copied": copied,
    }


def load(params: dict) -> dict:
    """
    params: ``{"project_file": str}``

    Returns the restored project plus absolute artifact paths into the
    sibling folder. Schema/parse problems return a structured error_code
    (never raise across JSON-RPC). Missing artifacts are a non-fatal
    ``ARTIFACT_MISSING`` warning carried alongside ``ok: True``.
    """
    pf = params.get("project_file")
    if not isinstance(pf, str) or not pf:
        raise TypeError("project_file must be a non-empty str")

    project_file = Path(pf)
    if not project_file.is_file():
        return _err("PROJECT_FILE_INVALID", f"project file not found: {pf}")
    try:
        with project_file.open(encoding="utf-8") as f:
            doc = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        return _err("PROJECT_FILE_INVALID", f"could not read project file: {exc}")

    if not isinstance(doc, dict):
        return _err("PROJECT_FILE_INVALID", "project file is not a JSON object")
    if doc.get("version") != PROJECT_SCHEMA_VERSION:
        return _err(
            "SCHEMA_VERSION_MISMATCH",
            f"expected schema version {PROJECT_SCHEMA_VERSION}, "
            f"got {doc.get('version')!r}",
            file_version=doc.get("version"),
            expected_version=PROJECT_SCHEMA_VERSION,
        )
    missing = [f for f in REQUIRED_PROJECT_FIELDS if f not in doc]
    if missing:
        return _err(
            "PROJECT_FILE_INVALID",
            f"project file missing required field(s): {missing}",
            missing=missing,
        )

    slug = slugify(str(doc["name"]))
    art_dir = _artifact_dir(project_file, slug)
    saved_art = doc.get("artifacts") or {}

    def _resolve(rel: str | None) -> str | None:
        if not rel:
            return None
        return str(art_dir / rel)

    preview_abs = _resolve(saved_art.get("preview_glb"))
    stl_abs = [_resolve(r) for r in (saved_art.get("stl_paths") or [])]

    warnings = [
        p for p in ([preview_abs] + stl_abs)
        if p is not None and not Path(p).is_file()
    ]

    edits = doc.get("edits") or []

    # Defence in depth: re-check the persisted edit chain against the same
    # Pydantic schema the LLM path uses (extra='forbid' + ranged fields). A
    # tampered/hand-edited .conjure3d.json can't inject code — the orchestrator
    # coerces types and whitelists op names — but a malformed chain would fail
    # silently mid-run. This surfaces it up front as a NON-FATAL signal so the
    # UI can warn before re-running, without breaking loads of otherwise-valid
    # projects (we never hard-reject here).
    edits_valid = True
    edits_validation_error = None
    try:
        validate_chain({"edits": edits})
    except Exception as exc:  # noqa: BLE001 — surface as a signal, never raise
        edits_valid = False
        edits_validation_error = str(exc)

    project = {
        "name": doc["name"],
        "prompt": doc["prompt"],
        "preview_task_id": doc["preview_task_id"],
        "source_glb": doc["source_glb"],
        "edits": edits,
        "color_split_mode": doc.get("color_split_mode") or "none",
        "last_sanity": doc.get("last_sanity"),
    }
    result = {
        "ok": True,
        "project": project,
        "artifact_dir": str(art_dir),
        "artifacts": {"preview_glb": preview_abs, "stl_paths": stl_abs},
        "edits_valid": edits_valid,
        "edits_validation_error": edits_validation_error,
    }
    if warnings:
        result["warning_code"] = "ARTIFACT_MISSING"
        result["missing_artifacts"] = warnings
    return result
