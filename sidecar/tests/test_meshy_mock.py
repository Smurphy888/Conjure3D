import os
import sys
import pathlib
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import meshy_mock
from main import dispatch


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


# ── dispatch integration ──────────────────────────────────────────────────────

def test_dispatch_generate_preview():
    req = {"jsonrpc": "2.0", "id": 1, "method": "meshy.generate_preview", "params": {"prompt": "vase"}}
    resp = dispatch(req)
    assert "error" not in resp
    assert resp["result"]["task_id"].startswith("mock-preview-")


def test_dispatch_poll_task_succeeds_on_third():
    gen_req = {"jsonrpc": "2.0", "id": 1, "method": "meshy.generate_preview", "params": {"prompt": "test"}}
    task_id = dispatch(gen_req)["result"]["task_id"]

    for i in range(2):
        r = dispatch({"jsonrpc": "2.0", "id": i + 2, "method": "meshy.poll_task", "params": {"task_id": task_id}})
        assert r["result"]["status"] == "PROCESSING"

    r = dispatch({"jsonrpc": "2.0", "id": 4, "method": "meshy.poll_task", "params": {"task_id": task_id}})
    assert r["result"]["status"] == "SUCCEEDED"


def test_dispatch_set_fixture():
    req = {"jsonrpc": "2.0", "id": 1, "method": "meshy.set_fixture", "params": {"name": "guitar"}}
    resp = dispatch(req)
    assert resp["result"]["fixture"] == "guitar"


def test_dispatch_refine():
    req = {"jsonrpc": "2.0", "id": 1, "method": "meshy.refine", "params": {"preview_task_id": "mock-preview-abc"}}
    resp = dispatch(req)
    assert "error" not in resp
    assert resp["result"]["task_id"].startswith("mock-refine-")
