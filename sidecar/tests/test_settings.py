import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from settings import DEFAULT_SETTINGS, read_settings, wizard_complete, write_settings


def test_read_missing_returns_defaults(tmp_path):
    p = tmp_path / "settings.json"
    result = read_settings(path=p)
    assert result["version"] == 1
    assert result["wizard"]["step_blender"] is False


def test_write_then_read_roundtrip(tmp_path):
    p = tmp_path / "settings.json"
    data = dict(DEFAULT_SETTINGS)
    data["wizard"]["step_blender"] = True
    write_settings(data, path=p)
    loaded = read_settings(path=p)
    assert loaded["wizard"]["step_blender"] is True
    assert loaded["version"] == 1


def test_write_creates_parent_dir(tmp_path):
    p = tmp_path / "nested" / "dir" / "settings.json"
    write_settings(dict(DEFAULT_SETTINGS), path=p)
    assert p.exists()


def test_read_invalid_json_returns_defaults(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("not json", encoding="utf-8")
    result = read_settings(path=p)
    assert result == DEFAULT_SETTINGS


def test_read_wrong_version_returns_defaults(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"version": 99, "wizard": {}}), encoding="utf-8")
    result = read_settings(path=p)
    assert result == DEFAULT_SETTINGS


def test_wizard_complete_false_by_default():
    assert wizard_complete(dict(DEFAULT_SETTINGS)) is False


def test_wizard_complete_true_when_all_steps_set():
    data = dict(DEFAULT_SETTINGS)
    data["wizard"] = {
        "step_blender": True,
        "step_addon": True,
        "step_socket": True,
        "step_bambu": True,
        "step_meshy": True,
    }
    assert wizard_complete(data) is True


def test_wizard_complete_false_when_one_step_missing():
    data = dict(DEFAULT_SETTINGS)
    data["wizard"] = {
        "step_blender": True,
        "step_addon": True,
        "step_socket": True,
        "step_bambu": True,
        "step_meshy": False,
    }
    assert wizard_complete(data) is False
