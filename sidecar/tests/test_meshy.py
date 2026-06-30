"""
Mock-only tests for the real Meshy client (Phase F Issue #23). The HTTP
layer is intercepted with the `responses` library — NO real network calls
are ever made (Meshy charges credits; the live path is the user's manual
acceptance per the Phase F gate).
"""
import os
import sys
import pathlib

import pytest
import requests
import responses

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import meshy


@pytest.fixture(autouse=True)
def fake_key(monkeypatch):
    """Deterministic API key — never touch the machine's real keyring."""
    monkeypatch.setattr(
        meshy.keyring, "get_password", lambda *a, **k: "test-key-abc"
    )


# ── source has no eager network import ────────────────────────────────────

def test_requests_imported_lazily_not_at_module_top():
    src = pathlib.Path(meshy.__file__).read_text()
    head = src.split("def _api_key")[0]
    assert "import requests" not in head  # only inside functions


# ── generate_preview ──────────────────────────────────────────────────────

@responses.activate
def test_generate_preview_returns_task_id_and_sends_bearer():
    responses.add(responses.POST, meshy.API_BASE,
                  json={"result": "task-prev-1"}, status=200)
    out = meshy.generate_preview({"prompt": "a brass vase"})
    assert out == {"task_id": "task-prev-1"}
    req = responses.calls[0].request
    assert req.headers["Authorization"] == "Bearer test-key-abc"
    import json
    body = json.loads(req.body)
    assert body["mode"] == "preview"
    assert body["prompt"] == "a brass vase"
    assert body["art_style"] == "realistic"  # default


@responses.activate
def test_generate_preview_passes_negative_prompt_when_given():
    responses.add(responses.POST, meshy.API_BASE,
                  json={"result": "t"}, status=200)
    meshy.generate_preview({
        "prompt": "x", "art_style": "sculpture", "negative_prompt": "low poly"
    })
    import json
    body = json.loads(responses.calls[0].request.body)
    assert body["art_style"] == "sculpture"
    assert body["negative_prompt"] == "low poly"


# ── refine ────────────────────────────────────────────────────────────────

@responses.activate
def test_refine_posts_preview_task_id():
    responses.add(responses.POST, meshy.API_BASE,
                  json={"result": "task-ref-9"}, status=200)
    out = meshy.refine({"preview_task_id": "task-prev-1"})
    assert out == {"task_id": "task-ref-9"}
    import json
    body = json.loads(responses.calls[0].request.body)
    assert body == {"mode": "refine", "preview_task_id": "task-prev-1"}


# ── poll_task status normalisation ────────────────────────────────────────

@responses.activate
def test_poll_in_progress_maps_to_processing():
    responses.add(responses.GET, f"{meshy.API_BASE}/t1",
                  json={"status": "IN_PROGRESS", "progress": 42}, status=200)
    assert meshy.poll_task({"task_id": "t1"}) == {
        "status": "PROCESSING", "progress": 42}


@responses.activate
def test_poll_succeeded_returns_glb_url():
    responses.add(
        responses.GET, f"{meshy.API_BASE}/t2",
        json={"status": "SUCCEEDED", "progress": 100,
              "model_urls": {"glb": "https://assets.meshy.ai/x.glb"}},
        status=200,
    )
    out = meshy.poll_task({"task_id": "t2"})
    assert out["status"] == "SUCCEEDED"
    assert out["progress"] == 100
    assert out["model_urls"]["glb"] == "https://assets.meshy.ai/x.glb"


@responses.activate
def test_poll_failed_surfaces_verbatim_error():
    responses.add(
        responses.GET, f"{meshy.API_BASE}/t3",
        json={"status": "FAILED", "progress": 0,
              "task_error": {"message": "prompt rejected by safety filter"}},
        status=200,
    )
    out = meshy.poll_task({"task_id": "t3"})
    assert out["status"] == "FAILED"
    assert out["task_error"] == "prompt rejected by safety filter"


# ── verbatim error surfacing, no retry ────────────────────────────────────

@responses.activate
def test_api_error_body_surfaced_verbatim_and_no_retry():
    body = '{"error":"insufficient credits","code":402}'
    responses.add(responses.POST, meshy.API_BASE, body=body, status=402)
    with pytest.raises(meshy.MeshyError) as ei:
        meshy.generate_preview({"prompt": "x"})
    assert str(ei.value) == body  # verbatim, unmodified
    assert len(responses.calls) == 1  # NO auto-retry


@responses.activate
def test_transport_error_surfaced_verbatim():
    responses.add(responses.POST, meshy.API_BASE,
                  body=requests.exceptions.ConnectionError("name resolution failed"))
    with pytest.raises(meshy.MeshyError) as ei:
        meshy.generate_preview({"prompt": "x"})
    assert "name resolution failed" in str(ei.value)
    assert len(responses.calls) == 1


def test_missing_api_key_raises_without_network(monkeypatch):
    monkeypatch.setattr(meshy.keyring, "get_password", lambda *a, **k: None)
    with pytest.raises(meshy.MeshyError, match="No Meshy API key"):
        meshy.generate_preview({"prompt": "x"})


# ── download_glb ──────────────────────────────────────────────────────────

@responses.activate
def test_download_glb_streams_to_disk_and_verifies_size(tmp_path):
    data = b"GLB-BINARY-PAYLOAD" * 1000
    url = "https://assets.meshy.ai/signed/model.glb"
    responses.add(responses.GET, url, body=data, status=200,
                  headers={"Content-Length": str(len(data))})
    dest = str(tmp_path / "model.glb")
    out = meshy.download_glb({"url": url, "dest": dest})
    assert out == {"path": dest, "bytes": len(data)}
    assert pathlib.Path(dest).read_bytes() == data
    assert not (tmp_path / "model.glb.part").exists()  # tmp cleaned up


@responses.activate
def test_download_glb_truncated_fails_cleanly_no_partial(tmp_path):
    # Server promises 999999 bytes, sends 5: urllib3 raises IncompleteRead.
    # Contract: a clean MeshyError, dest never created, .part removed.
    url = "https://assets.meshy.ai/signed/bad.glb"
    responses.add(responses.GET, url, body=b"short", status=200,
                  headers={"Content-Length": "999999"})
    dest = str(tmp_path / "bad.glb")
    with pytest.raises(meshy.MeshyError):
        meshy.download_glb({"url": url, "dest": dest})
    assert not pathlib.Path(dest).exists()
    assert not (tmp_path / "bad.glb.part").exists()


@responses.activate
def test_download_glb_empty_response_raises_and_cleans_up(tmp_path):
    # No Content-Length, zero bytes — explicit empty-file guard fires.
    url = "https://assets.meshy.ai/signed/empty.glb"
    responses.add(responses.GET, url, body=b"", status=200)
    dest = str(tmp_path / "empty.glb")
    with pytest.raises(meshy.MeshyError, match="empty file"):
        meshy.download_glb({"url": url, "dest": dest})
    assert not pathlib.Path(dest).exists()
    assert not (tmp_path / "empty.glb.part").exists()


@responses.activate
def test_download_glb_hosts_blocked_surfaced_verbatim(tmp_path):
    url = "https://assets.meshy.ai/signed/blocked.glb"
    responses.add(responses.GET, url,
                  body=requests.exceptions.ConnectionError(
                      "Failed to resolve 'assets.meshy.ai'"))
    dest = str(tmp_path / "blocked.glb")
    with pytest.raises(meshy.MeshyError, match="assets.meshy.ai"):
        meshy.download_glb({"url": url, "dest": dest})
    assert not (tmp_path / "blocked.glb.part").exists()
    assert len(responses.calls) == 1  # no retry on a blocked host
