"""Tests for mock edit.apply_chain (Phase D)."""
import pytest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

import meshy_mock
import orchestrator_mock


@pytest.fixture(autouse=True)
def reset_meshy():
    meshy_mock._reset()
    yield
    meshy_mock._reset()


def test_apply_chain_returns_vase_by_default():
    result = orchestrator_mock.apply_chain({"src_glb": "x.glb", "edits": [], "dst_dir": "/tmp"})
    assert result["preview_glb"].endswith("sample_vase.glb")


def test_apply_chain_returns_guitar_when_fixture_set():
    meshy_mock.set_fixture({"name": "guitar"})
    result = orchestrator_mock.apply_chain({"src_glb": "x.glb", "edits": [], "dst_dir": "/tmp"})
    assert result["preview_glb"].endswith("sample_guitar.glb")


def test_apply_chain_sanity_shape():
    result = orchestrator_mock.apply_chain({})
    sanity = result["sanity"]
    assert sanity["manifold"] is True
    assert sanity["single_component"] is True
    assert sanity["normals_outward"] is True
    assert sanity["longest_dim_under_limit"] is True
    assert len(sanity["dims_mm"]) == 3
    assert all(d > 0 for d in sanity["dims_mm"])


def test_apply_chain_has_required_keys():
    result = orchestrator_mock.apply_chain({})
    assert "preview_glb" in result
    assert "sanity" in result
    assert "stl_paths" in result
    assert isinstance(result["stl_paths"], list)


def test_apply_chain_fixture_path_exists():
    result = orchestrator_mock.apply_chain({})
    assert Path(result["preview_glb"]).exists()
