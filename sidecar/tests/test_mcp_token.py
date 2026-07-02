"""
Tests for mcp_token.py (shared-secret auth for the BlenderMCP socket) and
for the token's inclusion in every client payload.

The addon-side mirror of this logic lives inside blender_mcp.py (it must
stay self-contained in Blender); test_addon.py carries source-marker tests
that keep the two halves from drifting apart silently.
"""
import json
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import mcp_token  # noqa: E402


@pytest.fixture
def tmp_localappdata(tmp_path, monkeypatch):
    """Point LOCALAPPDATA at a temp dir so tests never touch the real
    per-user token."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path


def test_creates_64_hex_token(tmp_localappdata):
    tok = mcp_token.get_or_create_token()
    assert re.fullmatch(r"[0-9a-f]{64}", tok)
    assert (tmp_localappdata / "Conjure3D" / "mcp_token").is_file()


def test_second_call_returns_same_token(tmp_localappdata):
    a = mcp_token.get_or_create_token()
    b = mcp_token.get_or_create_token()
    assert a == b


def test_existing_token_is_read_not_replaced(tmp_localappdata):
    p = tmp_localappdata / "Conjure3D" / "mcp_token"
    p.parent.mkdir(parents=True)
    p.write_text("f" * 64, encoding="utf-8")
    assert mcp_token.get_or_create_token() == "f" * 64


def test_empty_token_file_is_regenerated(tmp_localappdata):
    p = tmp_localappdata / "Conjure3D" / "mcp_token"
    p.parent.mkdir(parents=True)
    p.write_text("", encoding="utf-8")
    tok = mcp_token.get_or_create_token()
    assert re.fullmatch(r"[0-9a-f]{64}", tok)


def test_token_path_falls_back_to_home(monkeypatch, tmp_path):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert mcp_token.token_path() == tmp_path / "Conjure3D" / "mcp_token"


# ── Token rides in every client payload ─────────────────────────────────────


def test_blender_client_payload_includes_token(tmp_localappdata):
    import blender_client
    cmd = json.loads(blender_client._payload("print('x')").decode("utf-8"))
    assert cmd["type"] == "execute_code"
    assert cmd["params"] == {"code": "print('x')"}
    assert re.fullmatch(r"[0-9a-f]{64}", cmd["token"])


def test_connection_ping_includes_token(tmp_localappdata):
    import connection
    cmd = json.loads(connection._ping_payload().decode())
    assert cmd["type"] == "get_scene_info"
    assert re.fullmatch(r"[0-9a-f]{64}", cmd["token"])


def test_client_and_ping_share_the_same_token(tmp_localappdata):
    import blender_client
    import connection
    a = json.loads(blender_client._payload("pass").decode())["token"]
    b = json.loads(connection._ping_payload().decode())["token"]
    assert a == b
