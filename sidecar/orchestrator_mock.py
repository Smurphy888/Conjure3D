"""
Mock orchestrator for edit.apply_chain — Phase D only.
Returns the current fixture GLB path with a green sanity stub.
No Blender ops, no file I/O. Phase E #22 replaces with real ops.
"""
from pathlib import Path

import meshy_mock as _meshy

_FIXTURE_DIR = Path(__file__).parent / "tests" / "fixtures"


def apply_chain(params: dict) -> dict:
    """Ignore edits; return current fixture GLB + stubbed sanity report."""
    fixture = _meshy._fixture
    preview_glb = str(_FIXTURE_DIR / f"sample_{fixture}.glb")
    return {
        "preview_glb": preview_glb,
        "sanity": {
            "manifold": True,
            "single_component": True,
            "normals_outward": True,
            "longest_dim_under_limit": True,
            "dims_mm": [80.0, 60.0, 60.0],
        },
        "stl_paths": [],
        "errors": [],
    }
