"""
Shared-secret token for the BlenderMCP socket (LAUNCH_AUDIT.md §1.2).

The addon's TCP server executes arbitrary Python sent to it. It binds to
loopback only, but loopback is shared by every process on the machine —
without authentication, any local process could run code inside Blender
with the user's privileges while the addon is connected.

The fix is a per-install shared secret in a file both sides can read:

    %LOCALAPPDATA%\\Conjure3D\\mcp_token

Whichever side starts first creates it (0-byte races resolve by both
sides re-reading the same final content thanks to the atomic replace);
the sidecar sends it as a top-level "token" field in every command, and
the addon rejects commands whose token doesn't match (constant-time
compare). Same-user processes can read the file — that's inherent to a
file-based handshake and acceptable: the threat killed here is OTHER
users' processes and sandboxed apps reaching the socket, plus any
remote-originated pivot that can hit loopback but not the filesystem.

The addon carries a mirrored copy of this logic (it must stay a single
self-contained .py inside Blender — it cannot import this module). If
you change the path or format here, change `_get_or_create_auth_token`
in sidecar/blender_addon/blender_mcp.py to match.
"""
import os
import secrets
from pathlib import Path

TOKEN_FILENAME = "mcp_token"


def token_path() -> Path:
    """%LOCALAPPDATA%\\Conjure3D\\mcp_token (home-dir fallback for dev/CI)."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "Conjure3D" / TOKEN_FILENAME


def get_or_create_token() -> str:
    """Read the shared token, creating it (64 hex chars, 256 bits) if absent.

    Atomic create via temp-file + os.replace so a concurrent first-run from
    the addon side can't observe a half-written token.
    """
    p = token_path()
    try:
        tok = p.read_text(encoding="utf-8").strip()
        if tok:
            return tok
    except (FileNotFoundError, OSError):
        pass

    p.parent.mkdir(parents=True, exist_ok=True)
    tok = secrets.token_hex(32)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(tok, encoding="utf-8")
    os.replace(tmp, p)
    # Re-read instead of returning our candidate: if two processes raced,
    # both end up using whichever replace landed last.
    return p.read_text(encoding="utf-8").strip()
