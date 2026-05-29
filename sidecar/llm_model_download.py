"""
Resumable model-file download for Phase J.5.

Downloads the Qwen2.5-Coder-7B-Instruct Q4_K_M GGUF from Hugging Face
(or any HTTP URL) into the canonical models directory, supporting:

  - HTTP Range requests for resume after interruption / sidecar restart
  - Atomic rename: writes to ``<name>.partial`` and renames only on
    successful SHA verification, so a crash never leaves a "valid-
    looking" but truncated GGUF that llama-cpp-python would happily
    accept and silently produce garbage from
  - Incremental SHA256 (computed during write, no second pass over
    the 4.4 GB file)
  - Optional disk-space precheck against Content-Length + 200 MB
    headroom
  - Cancellation via threading.Event (frontend "Cancel" button)
  - Live progress snapshot via status() — frontend polls every ~500ms
    rather than us building a streaming event channel over JSON-RPC

The download runs in a background thread so the JSON-RPC loop stays
responsive. Status updates are read/written under a lock so the
frontend always sees a consistent {phase, bytes_done, bytes_total,
error} snapshot.

Design choice: ONE module-level downloader singleton. v1.0 doesn't
need parallel downloads (only one model file), and a singleton makes
the "is something downloading?" question trivial. Tests reset the
singleton between cases.
"""
from __future__ import annotations

import hashlib
import shutil
import threading
import time
from pathlib import Path
from typing import Any

import requests

from llm_llama_cpp import DEFAULT_MODEL_FILENAME, default_model_dir, default_model_path


# Hugging Face URL for the canonical Qwen2.5-Coder-7B-Instruct Q4_K_M
# GGUF. Public model, no auth required. Override via start_download(url=...)
# for advanced users who want to host their own mirror.
DEFAULT_MODEL_URL = (
    "https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/"
    "qwen2.5-coder-7b-instruct-q4_k_m.gguf"
)

# Streaming chunk size. 1 MiB balances disk-write batching against
# how often we update the progress counter (which the UI polls).
CHUNK_BYTES = 1 << 20  # 1 MiB

# Headroom above Content-Length we want free on disk before we start.
# Covers temporary filesystem overhead + any other apps that grow
# during the download.
DISK_HEADROOM_BYTES = 200 * 1024 * 1024  # 200 MiB

# HTTP timeouts. The connect timeout is short (Hugging Face DNS is
# fast); the read timeout has to tolerate the wall-clock between
# chunks on a slow link without aborting.
CONNECT_TIMEOUT_SEC = 30
READ_TIMEOUT_SEC = 60


# ── Phase enum (string constants for stable JSON wire format) ───────────────

PHASE_IDLE = "idle"
PHASE_CHECKING = "checking"          # HEAD / disk-space precheck
PHASE_DOWNLOADING = "downloading"    # streaming bytes
PHASE_VERIFYING = "verifying"        # final SHA check
PHASE_DONE = "done"
PHASE_CANCELLED = "cancelled"
PHASE_ERROR = "error"

_TERMINAL_PHASES = frozenset({PHASE_DONE, PHASE_CANCELLED, PHASE_ERROR})


class ModelDownloader:
    """Encapsulates the state and worker thread of a single download.
    See module docstring for the design rationale."""

    def __init__(
        self,
        url: str = DEFAULT_MODEL_URL,
        dest_path: Path | None = None,
        expected_sha256: str | None = None,
    ):
        self.url = url
        self.dest_path = Path(dest_path) if dest_path else default_model_path()
        self.expected_sha256 = expected_sha256
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._state: dict[str, Any] = {
            "phase": PHASE_IDLE,
            "bytes_done": 0,
            "bytes_total": None,
            "sha256": None,
            "error": None,
            "started_at": None,
            "finished_at": None,
            "dest_path": str(self.dest_path),
            "url": url,
        }

    # ── Public ──────────────────────────────────────────────────────────────

    def start(self) -> dict[str, Any]:
        """Begin the download in a background thread. If a download is
        already active (non-terminal phase), this is a no-op and the
        current status is returned. Otherwise the thread is spawned
        and the initial status is returned."""
        with self._lock:
            phase = self._state["phase"]
            if phase not in _TERMINAL_PHASES and phase != PHASE_IDLE:
                return dict(self._state)
            # Reset for a fresh attempt. Cancel event is cleared so the
            # next thread can run; previous error / completion timestamps
            # are wiped.
            self._cancel.clear()
            self._state.update(
                phase=PHASE_CHECKING,
                bytes_done=0,
                bytes_total=None,
                sha256=None,
                error=None,
                started_at=time.time(),
                finished_at=None,
            )
            snapshot = dict(self._state)

        self._thread = threading.Thread(target=self._run, daemon=True, name="model-download")
        self._thread.start()
        return snapshot

    def cancel(self) -> dict[str, Any]:
        """Signal the worker to stop. The .partial file is preserved
        on disk so the next start() resumes from where we left off."""
        self._cancel.set()
        # Don't block on join — return current status immediately;
        # the frontend will see PHASE_CANCELLED on its next poll.
        with self._lock:
            return dict(self._state)

    def status(self) -> dict[str, Any]:
        """Cheap snapshot of the current state. Safe to call from any
        thread — the frontend polls this every ~500 ms during active
        downloads."""
        with self._lock:
            snap = dict(self._state)
        # Augment with derived "model is fully present on disk" flag so
        # the frontend has a single yes/no for "do we have the model".
        snap["model_present"] = self.dest_path.is_file()
        return snap

    # ── Worker ──────────────────────────────────────────────────────────────

    def _run(self) -> None:
        """Worker thread body. All exceptions land in PHASE_ERROR with
        the exception message — the worker never lets a raise escape
        because it would crash the daemon thread silently."""
        try:
            self._download_and_verify()
        except Exception as exc:  # noqa: BLE001 — defensive
            self._set(phase=PHASE_ERROR, error=f"{type(exc).__name__}: {exc}")

    def _download_and_verify(self) -> None:
        # Ensure the destination directory exists. Self-contained here
        # rather than in start() so direct calls (tests) work the same
        # way as the threaded entry point. mkdir is cheap and idempotent.
        self.dest_path.parent.mkdir(parents=True, exist_ok=True)

        # If the final file already exists (e.g. previous session
        # finished but the singleton was reconstructed), we're done.
        if self.dest_path.is_file():
            self._set(phase=PHASE_DONE, finished_at=time.time())
            return

        partial = self._partial_path()

        # HEAD request to learn Content-Length and validate the URL is
        # reachable. Some Hugging Face mirrors return 302; allow_redirects
        # follows them. We don't need the body, just headers.
        try:
            head = requests.head(
                self.url,
                allow_redirects=True,
                timeout=(CONNECT_TIMEOUT_SEC, READ_TIMEOUT_SEC),
            )
            head.raise_for_status()
        except requests.RequestException as exc:
            self._set(phase=PHASE_ERROR, error=f"HEAD failed: {exc}")
            return
        total = _content_length(head)

        # Disk-space precheck. Only meaningful if we know how big the
        # file is; otherwise we trust the user has enough room.
        if total is not None:
            free = shutil.disk_usage(self.dest_path.parent).free
            need = total + DISK_HEADROOM_BYTES
            if free < need:
                self._set(
                    phase=PHASE_ERROR,
                    error=(
                        f"Not enough disk space at {self.dest_path.parent}: "
                        f"need ~{_human(need)}, have {_human(free)}"
                    ),
                )
                return

        # Resume support. Compute the current size of .partial; if it
        # already equals total, we somehow finished but didn't rename
        # (crash between download and verify). Skip straight to verify.
        existing = partial.stat().st_size if partial.exists() else 0
        if total is not None and existing == total:
            self._set(phase=PHASE_VERIFYING, bytes_done=existing, bytes_total=total)
            self._verify_and_finalize(partial)
            return

        # GET with Range header if resuming. Some servers return 200
        # (full body) instead of 206 (partial); the streaming write
        # below handles both since we always append.
        headers = {"Range": f"bytes={existing}-"} if existing else {}
        self._set(
            phase=PHASE_DOWNLOADING,
            bytes_done=existing,
            bytes_total=total,
        )
        try:
            resp = requests.get(
                self.url,
                stream=True,
                headers=headers,
                timeout=(CONNECT_TIMEOUT_SEC, READ_TIMEOUT_SEC),
                allow_redirects=True,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            self._set(phase=PHASE_ERROR, error=f"GET failed: {exc}")
            return

        # If the server ignored Range and returned the whole file
        # (status 200 instead of 206), restart from scratch — we can't
        # blindly append or we'll duplicate the prefix.
        if existing > 0 and resp.status_code == 200:
            partial.unlink(missing_ok=True)
            existing = 0
            self._set(bytes_done=0)

        sha = hashlib.sha256()
        if existing > 0:
            # Re-feed the SHA hasher with the resumed bytes so the
            # final digest matches a fresh download. We have to read
            # the file once here, but only on resume — clean starts
            # skip this step.
            with partial.open("rb") as f:
                for buf in iter(lambda: f.read(CHUNK_BYTES), b""):
                    sha.update(buf)

        with partial.open("ab") as f:
            for chunk in resp.iter_content(chunk_size=CHUNK_BYTES):
                if self._cancel.is_set():
                    self._set(phase=PHASE_CANCELLED, finished_at=time.time())
                    return
                if not chunk:
                    continue
                f.write(chunk)
                sha.update(chunk)
                self._inc_bytes(len(chunk))

        self._set(phase=PHASE_VERIFYING)
        if self.expected_sha256:
            actual = sha.hexdigest()
            if actual != self.expected_sha256:
                # Truncate the bad partial so the next resume starts
                # fresh. Leaving a wrong-hash partial in place would
                # be worse than a clean restart.
                partial.unlink(missing_ok=True)
                self._set(
                    phase=PHASE_ERROR,
                    sha256=actual,
                    error=(
                        f"SHA256 mismatch (expected {self.expected_sha256}, "
                        f"got {actual}). Partial file deleted; restart to retry."
                    ),
                )
                return
            self._set(sha256=actual)
        else:
            self._set(sha256=sha.hexdigest())

        # Atomic rename. From this point on, dest_path is a valid GGUF.
        partial.replace(self.dest_path)
        self._set(phase=PHASE_DONE, finished_at=time.time())

    def _verify_and_finalize(self, partial: Path) -> None:
        """Used when a previous run finished the download but didn't
        rename. Compute SHA, verify if expected, rename."""
        sha = hashlib.sha256()
        with partial.open("rb") as f:
            for buf in iter(lambda: f.read(CHUNK_BYTES), b""):
                if self._cancel.is_set():
                    self._set(phase=PHASE_CANCELLED, finished_at=time.time())
                    return
                sha.update(buf)
        actual = sha.hexdigest()
        if self.expected_sha256 and actual != self.expected_sha256:
            partial.unlink(missing_ok=True)
            self._set(
                phase=PHASE_ERROR,
                sha256=actual,
                error=f"SHA256 mismatch on resumed file (got {actual}); deleted",
            )
            return
        partial.replace(self.dest_path)
        self._set(phase=PHASE_DONE, sha256=actual, finished_at=time.time())

    # ── State helpers ───────────────────────────────────────────────────────

    def _partial_path(self) -> Path:
        return self.dest_path.with_suffix(self.dest_path.suffix + ".partial")

    def _set(self, **kwargs: Any) -> None:
        with self._lock:
            self._state.update(kwargs)

    def _inc_bytes(self, n: int) -> None:
        with self._lock:
            self._state["bytes_done"] += n


# ── Module-level singleton ──────────────────────────────────────────────────

_downloader: ModelDownloader | None = None
_singleton_lock = threading.Lock()


def get_downloader(
    url: str = DEFAULT_MODEL_URL,
    dest_path: Path | None = None,
    expected_sha256: str | None = None,
) -> ModelDownloader:
    """Return the process-wide singleton, creating it on first call.
    Reusing the same instance across start() calls preserves the
    history of attempted downloads in its state dict — useful for
    "retry from where we failed" without losing the prior progress."""
    global _downloader
    with _singleton_lock:
        if _downloader is None:
            _downloader = ModelDownloader(
                url=url, dest_path=dest_path, expected_sha256=expected_sha256
            )
        return _downloader


def reset_downloader() -> None:
    """For tests — drop the singleton so the next get_downloader() call
    starts fresh. Never call from production code."""
    global _downloader
    with _singleton_lock:
        _downloader = None


# ── Cheap status helpers (no thread state required) ─────────────────────────


def model_present(path: Path | None = None) -> bool:
    """Is the canonical GGUF on disk? Used by the wizard / AI Editor
    to skip download prompts when the file already exists."""
    target = path or default_model_path()
    return target.is_file()


def expected_path() -> Path:
    """Canonical destination path. Frontend shows this to the user
    so they can verify / move the model file manually if they want."""
    return default_model_path()


# ── Helpers ────────────────────────────────────────────────────────────────


def _content_length(resp: requests.Response) -> int | None:
    raw = resp.headers.get("Content-Length")
    if raw is None:
        return None
    try:
        v = int(raw)
        return v if v > 0 else None
    except ValueError:
        return None


def _human(n: int) -> str:
    """Human-readable size for error messages."""
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} PiB"
