"""
Tests for the Tripo AI client (tripo.py). HTTP layer mocked with the
`responses` library — no real network calls are ever made (Tripo charges
credits per generation, same policy as Meshy).
"""
import os
import sys
import json
import pathlib

import pytest
import requests
import responses

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tripo


@pytest.fixture(autouse=True)
def fake_key(monkeypatch):
    """Deterministic API key — never touch the machine's real keyring."""
    monkeypatch.setattr(
        tripo.keyring, "get_password", lambda *a, **k: "tsk_test-key-abc"
    )


# ── lazy import guard ────────────────────────────────────────────────────────

def test_requests_imported_lazily_not_at_module_top():
    src = pathlib.Path(tripo.__file__).read_text()
    head = src.split("def _api_key")[0]
    assert "import requests" not in head


# ── generate_preview ─────────────────────────────────────────────────────────

@responses.activate
def test_generate_preview_returns_task_id_and_sends_bearer():
    responses.add(
        responses.POST, tripo.API_BASE,
        json={"code": 0, "data": {"task_id": "tripo-task-1"}},
        status=200,
    )
    out = tripo.generate_preview({"prompt": "a brass vase"})
    assert out == {"task_id": "tripo-task-1"}
    req = responses.calls[0].request
    assert req.headers["Authorization"] == "Bearer tsk_test-key-abc"
    body = json.loads(req.body)
    assert body["type"] == "text_to_model"
    assert body["prompt"] == "a brass vase"
    assert "negative_prompt" not in body  # only sent when provided


@responses.activate
def test_generate_preview_passes_negative_prompt_when_given():
    responses.add(
        responses.POST, tripo.API_BASE,
        json={"code": 0, "data": {"task_id": "t"}},
        status=200,
    )
    tripo.generate_preview({"prompt": "x", "negative_prompt": "low poly"})
    body = json.loads(responses.calls[0].request.body)
    assert body["negative_prompt"] == "low poly"


# ── poll_task status normalisation ───────────────────────────────────────────

@responses.activate
def test_poll_processing_maps_to_processing():
    responses.add(
        responses.GET, f"{tripo.API_BASE}/t1",
        json={"code": 0, "data": {"status": "processing", "progress": 42}},
        status=200,
    )
    out = tripo.poll_task({"task_id": "t1"})
    assert out == {"status": "PROCESSING", "progress": 42}


@responses.activate
def test_poll_queued_maps_to_processing():
    responses.add(
        responses.GET, f"{tripo.API_BASE}/t-q",
        json={"code": 0, "data": {"status": "queued", "progress": 0}},
        status=200,
    )
    out = tripo.poll_task({"task_id": "t-q"})
    assert out["status"] == "PROCESSING"


@responses.activate
def test_poll_success_returns_pbr_glb_url():
    responses.add(
        responses.GET, f"{tripo.API_BASE}/t2",
        json={
            "code": 0,
            "data": {
                "status": "success",
                "progress": 100,
                "output": {
                    "pbr_model": "https://cdn.tripo3d.ai/x-pbr.glb",
                    "model": "https://cdn.tripo3d.ai/x.glb",
                },
            },
        },
        status=200,
    )
    out = tripo.poll_task({"task_id": "t2"})
    assert out["status"] == "SUCCEEDED"
    assert out["progress"] == 100
    # pbr_model is preferred over model
    assert out["model_urls"]["glb"] == "https://cdn.tripo3d.ai/x-pbr.glb"


@responses.activate
def test_poll_success_falls_back_to_model_when_pbr_absent():
    responses.add(
        responses.GET, f"{tripo.API_BASE}/t2b",
        json={
            "code": 0,
            "data": {
                "status": "success",
                "progress": 100,
                "output": {"model": "https://cdn.tripo3d.ai/x.glb"},
            },
        },
        status=200,
    )
    out = tripo.poll_task({"task_id": "t2b"})
    assert out["model_urls"]["glb"] == "https://cdn.tripo3d.ai/x.glb"


@responses.activate
def test_poll_failed_surfaces_verbatim_error():
    responses.add(
        responses.GET, f"{tripo.API_BASE}/t3",
        json={
            "code": 0,
            "data": {
                "status": "failed",
                "progress": 0,
                "message": "prompt rejected by safety filter",
            },
        },
        status=200,
    )
    out = tripo.poll_task({"task_id": "t3"})
    assert out["status"] == "FAILED"
    assert out["task_error"] == "prompt rejected by safety filter"


# ── error surfacing, no retry ────────────────────────────────────────────────

@responses.activate
def test_api_error_body_surfaced_verbatim_and_no_retry():
    body = '{"error":"insufficient credits","code":402}'
    responses.add(responses.POST, tripo.API_BASE, body=body, status=402)
    with pytest.raises(tripo.TripoError) as ei:
        tripo.generate_preview({"prompt": "x"})
    assert str(ei.value) == body
    assert len(responses.calls) == 1  # NO auto-retry


@responses.activate
def test_transport_error_surfaced_verbatim():
    responses.add(
        responses.POST, tripo.API_BASE,
        body=requests.exceptions.ConnectionError("name resolution failed"),
    )
    with pytest.raises(tripo.TripoError) as ei:
        tripo.generate_preview({"prompt": "x"})
    assert "name resolution failed" in str(ei.value)
    assert len(responses.calls) == 1


def test_missing_api_key_raises_without_network(monkeypatch):
    monkeypatch.setattr(tripo.keyring, "get_password", lambda *a, **k: None)
    with pytest.raises(tripo.TripoError, match="No Tripo AI API key"):
        tripo.generate_preview({"prompt": "x"})


# ── download_glb ─────────────────────────────────────────────────────────────

@responses.activate
def test_download_glb_streams_to_disk_and_verifies_size(tmp_path):
    data = b"GLB-BINARY-PAYLOAD" * 1000
    url = "https://cdn.tripo3d.ai/signed/model.glb"
    responses.add(responses.GET, url, body=data, status=200,
                  headers={"Content-Length": str(len(data))})
    dest = str(tmp_path / "model.glb")
    out = tripo.download_glb({"url": url, "dest": dest})
    assert out == {"path": dest, "bytes": len(data)}
    assert pathlib.Path(dest).read_bytes() == data
    assert not (tmp_path / "model.glb.part").exists()


@responses.activate
def test_download_glb_truncated_fails_cleanly(tmp_path):
    url = "https://cdn.tripo3d.ai/signed/bad.glb"
    responses.add(responses.GET, url, body=b"short", status=200,
                  headers={"Content-Length": "999999"})
    dest = str(tmp_path / "bad.glb")
    with pytest.raises(tripo.TripoError):
        tripo.download_glb({"url": url, "dest": dest})
    assert not pathlib.Path(dest).exists()
    assert not (tmp_path / "bad.glb.part").exists()


@responses.activate
def test_download_glb_empty_response_raises_and_cleans_up(tmp_path):
    url = "https://cdn.tripo3d.ai/signed/empty.glb"
    responses.add(responses.GET, url, body=b"", status=200)
    dest = str(tmp_path / "empty.glb")
    with pytest.raises(tripo.TripoError, match="empty file"):
        tripo.download_glb({"url": url, "dest": dest})
    assert not pathlib.Path(dest).exists()
