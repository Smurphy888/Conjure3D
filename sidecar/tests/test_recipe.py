"""
Tests for recipe.py (Phase K).

Covers filament-count policy per color_split mode, confirming that the
recipe Python source stays in sync with Export.tsx's expected counts.

Regression for Issue #12: quarter mode was previously grouped with zebra
and emitted 2 filament slots. Quarter is now a pure geometric split with
no colour change → 1 filament.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from recipe import build_recipe


def test_none_mode_uses_one_filament():
    r = build_recipe(object_type="solid_decorative", color_split_mode="none")
    assert len(r.filament_settings_id) == 1
    assert len(r.filament_colour) == 1


def test_zebra_mode_uses_two_filaments():
    r = build_recipe(object_type="solid_decorative", color_split_mode="zebra")
    assert len(r.filament_settings_id) == 2
    assert len(r.filament_colour) == 2


def test_quarter_mode_uses_one_filament():
    """Quarter is a pure geometric split — no colour change, 1 filament.
    Regression for: quarter was previously treated like zebra (2 filaments)."""
    for otype in ("solid_decorative", "vase", "flat_part"):
        r = build_recipe(object_type=otype, color_split_mode="quarter")
        assert len(r.filament_settings_id) == 1, f"failed for object_type={otype!r}"
        assert len(r.filament_colour) == 1, f"failed for object_type={otype!r}"


def test_filament_settings_match_colour_count():
    for mode in ("none", "zebra", "quarter"):
        r = build_recipe(object_type="solid_decorative", color_split_mode=mode)
        assert len(r.filament_settings_id) == len(r.filament_colour), (
            f"mismatch for mode={mode!r}"
        )
