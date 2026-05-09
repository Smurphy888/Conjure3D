"""
Mock Meshy commands for dev and testing.
No network calls — returns fixture GLB paths from sidecar/tests/fixtures/.
"""
import uuid
from pathlib import Path

_FIXTURE_DIR = Path(__file__).parent / "tests" / "fixtures"
_fixture: str = "vase"
_poll_counts: dict[str, int] = {}


def _reset() -> None:
    """Test helper — clears poll state and resets fixture to vase."""
    global _fixture
    _fixture = "vase"
    _poll_counts.clear()


def generate_preview(params: dict) -> dict:
    task_id = f"mock-preview-{uuid.uuid4().hex[:8]}"
    _poll_counts[task_id] = 0
    return {"task_id": task_id}


def poll_task(params: dict) -> dict:
    task_id = params["task_id"]
    count = _poll_counts.get(task_id, 0) + 1
    _poll_counts[task_id] = count
    if count >= 3:
        glb_path = str(_FIXTURE_DIR / f"sample_{_fixture}.glb")
        return {"status": "SUCCEEDED", "progress": 100, "model_urls": {"glb": glb_path}}
    return {"status": "PROCESSING", "progress": 33 * count}


def refine(params: dict) -> dict:
    task_id = f"mock-refine-{uuid.uuid4().hex[:8]}"
    _poll_counts[task_id] = 0
    return {"task_id": task_id}


def set_fixture(params: dict) -> dict:
    global _fixture
    name = params.get("name", "vase")
    if name not in ("vase", "guitar"):
        raise ValueError(f"Unknown fixture: {name!r}. Must be 'vase' or 'guitar'.")
    _fixture = name
    return {"ok": True, "fixture": name}
