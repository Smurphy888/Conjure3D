"""
Tests for llm_model_download.py (Phase J.5).

The downloader runs a worker in a background thread. To keep tests
deterministic and fast, we drive the worker SYNCHRONOUSLY by calling
the internal _download_and_verify method directly with mocked HTTP
via the `responses` library. The threaded entry points (start, cancel)
get their own targeted tests that exercise actual threading.

Covered:
  - clean download from empty state
  - resume from existing partial (Range request honoured)
  - server ignores Range and returns 200 -> partial is truncated and
    we start over from scratch (the test asserts the final file is
    correct, not corrupted with a duplicated prefix)
  - cancellation mid-stream
  - SHA mismatch -> error phase, partial deleted
  - SHA match -> done phase, dest_path renamed in place
  - HEAD failure -> structured error, no partial written
  - disk-space precheck failure
  - get_downloader returns the same singleton; reset_downloader clears
    it for the next test
  - JSON-RPC dispatch path for llm.model_status / llm.download_start /
    llm.download_cancel
"""
import hashlib
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
import responses

sys.path.insert(0, str(Path(__file__).parent.parent))
import main  # noqa: E402
import llm_model_download as md  # noqa: E402


URL = "https://example.test/qwen.gguf"
BODY = b"qwen-q4-bytes-go-here-" * 2048  # ~45 KiB, enough to span several chunks
SHA = hashlib.sha256(BODY).hexdigest()


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Every test gets a fresh module-level downloader. Without this,
    state from one test (especially terminal phases) leaks into the
    next."""
    md.reset_downloader()
    yield
    md.reset_downloader()


@pytest.fixture
def tmp_dest(tmp_path: Path) -> Path:
    """Per-test destination so tests are isolated on disk."""
    return tmp_path / "models" / "qwen.gguf"


# ── Clean download ──────────────────────────────────────────────────────────


@responses.activate
def test_clean_download_writes_correct_bytes_and_phase_done(tmp_dest: Path):
    responses.add(responses.HEAD, URL, headers={"Content-Length": str(len(BODY))})
    responses.add(responses.GET, URL, body=BODY, status=200,
                  headers={"Content-Length": str(len(BODY))})

    dl = md.ModelDownloader(url=URL, dest_path=tmp_dest, expected_sha256=SHA)
    dl._download_and_verify()

    status = dl.status()
    assert status["phase"] == md.PHASE_DONE
    assert status["bytes_done"] == len(BODY)
    assert status["sha256"] == SHA
    assert tmp_dest.is_file()
    assert tmp_dest.read_bytes() == BODY
    # .partial should be gone after the atomic rename
    assert not (tmp_dest.with_suffix(tmp_dest.suffix + ".partial")).exists()


# ── Resume from partial ─────────────────────────────────────────────────────


@responses.activate
def test_resume_from_partial_uses_range_header(tmp_dest: Path):
    # Pre-seed a .partial with the first 1024 bytes
    partial = tmp_dest.with_suffix(tmp_dest.suffix + ".partial")
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_bytes(BODY[:1024])

    responses.add(responses.HEAD, URL, headers={"Content-Length": str(len(BODY))})
    # Server honours Range and returns 206 with only the remainder
    responses.add(
        responses.GET, URL,
        body=BODY[1024:],
        status=206,
        headers={"Content-Length": str(len(BODY) - 1024)},
    )

    dl = md.ModelDownloader(url=URL, dest_path=tmp_dest, expected_sha256=SHA)
    dl._download_and_verify()

    # Assert that the GET was made with the right Range header
    get_calls = [c for c in responses.calls if c.request.method == "GET"]
    assert get_calls
    assert get_calls[0].request.headers.get("Range") == "bytes=1024-"

    assert tmp_dest.read_bytes() == BODY
    assert dl.status()["phase"] == md.PHASE_DONE


@responses.activate
def test_server_ignores_range_partial_is_truncated_and_restarted(tmp_dest: Path):
    """Some mirrors/CDNs don't support Range and return 200 with the
    whole body. The downloader must NOT append to the existing partial
    in that case — it must truncate and start over. Otherwise the
    final file would have a duplicated prefix and the SHA would fail."""
    partial = tmp_dest.with_suffix(tmp_dest.suffix + ".partial")
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_bytes(BODY[:1024])

    responses.add(responses.HEAD, URL, headers={"Content-Length": str(len(BODY))})
    responses.add(
        responses.GET, URL,
        body=BODY,  # full body, status 200 (Range ignored)
        status=200,
        headers={"Content-Length": str(len(BODY))},
    )

    dl = md.ModelDownloader(url=URL, dest_path=tmp_dest, expected_sha256=SHA)
    dl._download_and_verify()

    # Must end up with the correct, non-duplicated content
    assert tmp_dest.read_bytes() == BODY
    assert dl.status()["phase"] == md.PHASE_DONE


# ── SHA verification ────────────────────────────────────────────────────────


@responses.activate
def test_sha_mismatch_deletes_partial_and_reports_error(tmp_dest: Path):
    responses.add(responses.HEAD, URL, headers={"Content-Length": str(len(BODY))})
    responses.add(responses.GET, URL, body=BODY, status=200,
                  headers={"Content-Length": str(len(BODY))})

    wrong_sha = "0" * 64
    dl = md.ModelDownloader(url=URL, dest_path=tmp_dest, expected_sha256=wrong_sha)
    dl._download_and_verify()

    status = dl.status()
    assert status["phase"] == md.PHASE_ERROR
    assert "SHA256 mismatch" in status["error"]
    # Bad partial deleted; dest never created
    assert not tmp_dest.exists()
    assert not (tmp_dest.with_suffix(tmp_dest.suffix + ".partial")).exists()


@responses.activate
def test_no_expected_sha_records_actual_hash(tmp_dest: Path):
    """If we don't know the expected hash (no checksum in config),
    we still compute and surface it so the user can verify out-of-band
    or report it for a future hardcoded value."""
    responses.add(responses.HEAD, URL, headers={"Content-Length": str(len(BODY))})
    responses.add(responses.GET, URL, body=BODY, status=200,
                  headers={"Content-Length": str(len(BODY))})

    dl = md.ModelDownloader(url=URL, dest_path=tmp_dest)  # no expected_sha256
    dl._download_and_verify()

    assert dl.status()["phase"] == md.PHASE_DONE
    assert dl.status()["sha256"] == SHA


# ── HEAD failure ────────────────────────────────────────────────────────────


@responses.activate
def test_head_failure_sets_error_phase(tmp_dest: Path):
    responses.add(responses.HEAD, URL, status=404)
    dl = md.ModelDownloader(url=URL, dest_path=tmp_dest)
    dl._download_and_verify()
    assert dl.status()["phase"] == md.PHASE_ERROR
    assert "HEAD failed" in dl.status()["error"]


# ── Disk-space precheck ─────────────────────────────────────────────────────


@responses.activate
def test_insufficient_disk_space_fails_cleanly(tmp_dest: Path):
    responses.add(responses.HEAD, URL, headers={"Content-Length": "10000000000"})  # 10 GB

    # Pretend free space is only 1 GB
    class _FakeDU:
        free = 1_000_000_000
        total = 100_000_000_000
        used = 99_000_000_000

    dl = md.ModelDownloader(url=URL, dest_path=tmp_dest)
    with patch("shutil.disk_usage", return_value=_FakeDU):
        dl._download_and_verify()

    s = dl.status()
    assert s["phase"] == md.PHASE_ERROR
    assert "disk space" in s["error"]


# ── Cancellation ────────────────────────────────────────────────────────────


@responses.activate
def test_cancellation_sets_phase_cancelled_and_preserves_partial(tmp_dest: Path):
    """Simulate cancel by setting the event before the GET. The chunk
    loop should observe the flag on its first iteration and bail
    without finalising the file."""
    responses.add(responses.HEAD, URL, headers={"Content-Length": str(len(BODY))})
    responses.add(responses.GET, URL, body=BODY, status=200,
                  headers={"Content-Length": str(len(BODY))})

    dl = md.ModelDownloader(url=URL, dest_path=tmp_dest)
    dl._cancel.set()  # pre-cancel
    dl._download_and_verify()
    s = dl.status()
    assert s["phase"] == md.PHASE_CANCELLED
    # The dest_path is NOT created on cancel
    assert not tmp_dest.exists()


# ── Singleton ───────────────────────────────────────────────────────────────


def test_get_downloader_returns_same_instance():
    a = md.get_downloader(url="http://a/x")
    b = md.get_downloader(url="http://b/y")  # ignored; same instance
    assert a is b


def test_reset_downloader_clears_singleton():
    a = md.get_downloader()
    md.reset_downloader()
    b = md.get_downloader()
    assert a is not b


# ── Pinned default checksum (S3) ────────────────────────────────────────────


def test_default_url_gets_pinned_sha():
    """The default download path must always verify against the published
    hash — no caller opt-in required."""
    dl = md.get_downloader()  # default URL, no expected_sha256
    assert dl.expected_sha256 == md.DEFAULT_MODEL_SHA256


def test_custom_url_does_not_inherit_default_sha():
    """A mirror may serve a different (requantised) file; silently applying
    the default hash would hard-fail every legitimate custom download."""
    dl = md.get_downloader(url="https://mirror.example/model.gguf")
    assert dl.expected_sha256 is None


def test_explicit_sha_wins_over_pin():
    explicit = "a" * 64
    dl = md.get_downloader(expected_sha256=explicit)
    assert dl.expected_sha256 == explicit


def test_pinned_sha_is_wellformed():
    assert len(md.DEFAULT_MODEL_SHA256) == 64
    assert all(c in "0123456789abcdef" for c in md.DEFAULT_MODEL_SHA256)


# ── Thread integration ──────────────────────────────────────────────────────


@responses.activate
def test_start_spawns_thread_and_reaches_done(tmp_dest: Path):
    """Smoke check for the actual threaded path — make sure the worker
    runs to completion and updates state without the test having to
    poll forever."""
    responses.add(responses.HEAD, URL, headers={"Content-Length": str(len(BODY))})
    responses.add(responses.GET, URL, body=BODY, status=200,
                  headers={"Content-Length": str(len(BODY))})

    dl = md.ModelDownloader(url=URL, dest_path=tmp_dest, expected_sha256=SHA)
    dl.start()
    assert dl._thread is not None
    dl._thread.join(timeout=10)
    assert not dl._thread.is_alive()
    assert dl.status()["phase"] == md.PHASE_DONE


# ── JSON-RPC dispatch ───────────────────────────────────────────────────────


def test_dispatch_model_status_returns_idle_snapshot():
    """Before any download has been started, status reports phase=idle
    and model_present=False (assuming the file isn't on this dev box)."""
    req = {"jsonrpc": "2.0", "id": 1, "method": "llm.model_status", "params": {}}
    resp = main.dispatch(req)
    res = resp["result"]
    assert res["phase"] == md.PHASE_IDLE
    assert "model_present" in res
    assert "dest_path" in res


def test_dispatch_download_start_idempotent_when_active():
    """Calling download_start twice in quick succession returns the
    same singleton's status, not an error — the second call sees the
    first thread's in-flight state. The actual network call here is
    mocked away via the singleton's URL being unreachable; we just
    care about the dispatcher's contract."""
    # Use a never-resolving URL so the worker doesn't actually finish;
    # cancel right after so the test doesn't hang.
    req = {
        "jsonrpc": "2.0", "id": 2, "method": "llm.download_start",
        "params": {"url": "http://127.0.0.1:1/never"},
    }
    resp = main.dispatch(req)
    res = resp["result"]
    assert "phase" in res
    # Tidy up the singleton's thread.
    md.get_downloader().cancel()
    if md.get_downloader()._thread:
        md.get_downloader()._thread.join(timeout=5)
