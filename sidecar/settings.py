import json
import os
from pathlib import Path

_SETTINGS_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Conjure3D"
_SETTINGS_PATH = _SETTINGS_DIR / "settings.json"

DEFAULT_SETTINGS: dict = {
    "version": 1,
    "wizard": {
        "step_blender": False,
        "step_addon": False,
        "step_socket": False,
        "step_bambu": False,
        "step_meshy": False,
    },
    "bambu_path": None,
    "generation_provider": "meshy",
    # Which backend generates edit chains in the AI Editor. "local" = bundled
    # llama.cpp (falls back to the keyword mock if it can't load); "openrouter"
    # = cloud. Distinct from generation_provider (Meshy/Tripo, which makes the
    # 3D *model*). llm_model is the OpenRouter model id (non-Anthropic).
    "llm_provider": "local",
    "llm_model": None,
}


def _settings_path() -> Path:
    return _SETTINGS_PATH


def read_settings(path: Path | None = None) -> dict:
    p = path or _settings_path()
    if not p.exists():
        return dict(DEFAULT_SETTINGS)
    try:
        with p.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or data.get("version") != 1:
            return dict(DEFAULT_SETTINGS)
        return data
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_SETTINGS)


def write_settings(data: dict, path: Path | None = None) -> None:
    p = path or _settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def wizard_complete(settings: dict) -> bool:
    w = settings.get("wizard", {})
    return all(
        w.get(k, False)
        for k in ("step_blender", "step_addon", "step_socket", "step_bambu", "step_meshy")
    )
