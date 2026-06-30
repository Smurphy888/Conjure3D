import os
import sys
import pathlib
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import meshy_mock

# NOTE: this file used to import `dispatch` from main.py and exercise the
# JSON-RPC wiring for the meshy.* methods. That wiring was changed in Phase F
# (main.py:18 → `import meshy as _meshy`, the REAL Meshy API). Routing test
# requests through dispatch() now hits the live Meshy service: it spends
# credits and the assertions (mock-preview-*, mock-refine-*) fail by
# construction. The four `test_dispatch_*` cases below are kept as a thin
# guard that the mock module's public surface still returns mock-shaped IDs;
# they bypass dispatch entirely. If you want to re-cover the dispatch wiring,
# do it in a separate file with a monkeypatched _meshy fixture so it can't
# accidentally regress into firing live calls.


def setup_function():
    meshy_mock._reset()


# ── no network calls ───────────────────────────────────────────────────────────

def test_no_requests_in_source():
    src = pathlib.Path(meshy_mock.__file__).read_text()
    assert "import requests" not in src
    assert "requests.get" not in src
    assert "requests.post" not in src


# ── generate_preview ──────────────────────────────────────────────────────────

def test_generate_preview_returns_task_id():
    result = meshy_mock.generate_preview({"prompt": "a vase", "art_style": "realistic"})
    assert result["task_id"].startswith("mock-preview-")


def test_generate_preview_unique_ids():
    r1 = meshy_mock.generate_preview({"prompt": "a"})
    r2 = meshy_mock.generate_preview({"prompt": "b"})
    assert r1["task_id"] != r2["task_id"]


# ── poll_task ─────────────────────────────────────────────────────────────────

def test_poll_task_processing_then_succeeded_vase():
    gen = meshy_mock.generate_preview({"prompt": "test"})
    task_id = gen["task_id"]

    r1 = meshy_mock.poll_task({"task_id": task_id})
    assert r1["status"] == "PROCESSING"

    r2 = meshy_mock.poll_task({"task_id": task_id})
    assert r2["status"] == "PROCESSING"

    r3 = meshy_mock.poll_task({"task_id": task_id})
    assert r3["status"] == "SUCCEEDED"
    assert r3["progress"] == 100
    assert "model_urls" in r3
    assert r3["model_urls"]["glb"].endswith("sample_vase.glb")


def test_poll_task_fixture_guitar():
    meshy_mock.set_fixture({"name": "guitar"})
    gen = meshy_mock.generate_preview({"prompt": "guitar"})
    task_id = gen["task_id"]
    for _ in range(3):
        r = meshy_mock.poll_task({"task_id": task_id})
    assert r["status"] == "SUCCEEDED"
    assert r["model_urls"]["glb"].endswith("sample_guitar.glb")


def test_poll_task_stays_succeeded_after_third():
    gen = meshy_mock.generate_preview({"prompt": "x"})
    task_id = gen["task_id"]
    for _ in range(5):
        r = meshy_mock.poll_task({"task_id": task_id})
    assert r["status"] == "SUCCEEDED"


# ── refine ────────────────────────────────────────────────────────────────────

def test_refine_returns_new_task_id():
    gen = meshy_mock.generate_preview({"prompt": "test"})
    ref = meshy_mock.refine({"preview_task_id": gen["task_id"]})
    assert ref["task_id"].startswith("mock-refine-")
    assert ref["task_id"] != gen["task_id"]


def test_refine_polls_to_succeeded():
    ref = meshy_mock.refine({"preview_task_id": "some-id"})
    task_id = ref["task_id"]
    for _ in range(3):
        r = meshy_mock.poll_task({"task_id": task_id})
    assert r["status"] == "SUCCEEDED"
    assert r["model_urls"]["glb"].endswith("sample_vase.glb")


# ── set_fixture ───────────────────────────────────────────────────────────────

def test_set_fixture_guitar_and_back_to_vase():
    meshy_mock.set_fixture({"name": "guitar"})
    assert meshy_mock._fixture == "guitar"
    meshy_mock.set_fixture({"name": "vase"})
    assert meshy_mock._fixture == "vase"


def test_set_fixture_invalid_raises():
    with pytest.raises(ValueError):
        meshy_mock.set_fixture({"name": "invalid"})


# ── mock public surface (formerly dispatch integration) ──────────────────────
# Names kept stable so CI history / pytest selectors don't churn. Bodies now
# exercise meshy_mock directly; see the file-level NOTE above for why.

def test_dispatch_generate_preview():
    resp = meshy_mock.generate_preview({"prompt": "vase"})
    assert resp["task_id"].startswith("mock-preview-")


def test_dispatch_poll_task_succeeds_on_third():
    task_id = meshy_mock.generate_preview({"prompt": "test"})["task_id"]
    for _ in range(2):
        r = meshy_mock.poll_task({"task_id": task_id})
        assert r["status"] == "PROCESSING"
    r = meshy_mock.poll_task({"task_id": task_id})
    assert r["status"] == "SUCCEEDED"


def test_dispatch_set_fixture():
    resp = meshy_mock.set_fixture({"name": "guitar"})
    assert resp["fixture"] == "guitar"


def test_dispatch_refine():
    resp = meshy_mock.refine({"preview_task_id": "mock-preview-abc"})
    assert resp["task_id"].startswith("mock-refine-")
