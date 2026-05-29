"""
Per-object-type recipe lookup (Phase K).

Mirrors the TypeScript ``recipe()`` function in src/screens/Export.tsx so
that the JSON shown in the UI as guidance and the JSON baked into the
.3mf are derived from the SAME catalogue. This module is the Python
source of truth; if you change a value here you must update Export.tsx
to match (or vice versa). The two grow apart silently if not pinned.

The output is a :class:`threemf_writer.RecipeSettings` instance, ready
to hand to ``write_3mf``. Filament list defaults to one entry; callers
override based on color_split mode.
"""
from __future__ import annotations

from threemf_writer import RecipeSettings


# Colour palette for filament_colour. Matches the Conjure_Red /
# Conjure_Yellow shades used in ops/color_split.py so what the user
# sees in Blender's viewport is what they get in Bambu's plate view.
COLOR_RED_HEX = "#CC1A1A"
COLOR_YELLOW_HEX = "#E6CC00"
FILAMENT_BAMBU_PLA = "Bambu PLA Basic"


def build_recipe(
    object_type: str,
    longest_mm: float | None = None,
    color_split_mode: str = "none",
) -> RecipeSettings:
    """Return the slicer recipe for an object type. Mirrors Export.tsx.

    object_type: "vase" | "solid_decorative" | "flat_part"
    longest_mm:  for solid_decorative, a longest dim > 100mm switches
                 the brim from "recommended" to required (we always
                 emit a brim either way since the .3mf has to commit;
                 the UI panel uses the same input to label the brim
                 as recommended/required for STL-mode users).
    color_split_mode: "none" | "zebra" | "quarter". Determines how
                 many filament slots we pre-configure.
    """
    if object_type == "vase":
        base = RecipeSettings(
            wall_loops=5,
            sparse_infill_density=0,
            sparse_infill_pattern="gyroid",
            top_shell_layers=0,
            bottom_shell_layers=4,
            brim_type="no_brim",
            brim_width=0.0,
            enable_support=False,
            spiral_mode=True,
        )
    elif object_type == "flat_part":
        base = RecipeSettings(
            wall_loops=4,
            sparse_infill_density=20,
            sparse_infill_pattern="gyroid",
            top_shell_layers=4,
            bottom_shell_layers=4,
            brim_type="outer_only",
            brim_width=3.0,
            enable_support=False,
            spiral_mode=False,
        )
    else:  # solid_decorative (and the conservative default)
        # 5mm brim recommended at any size; required > 100mm. The .3mf
        # always emits 5mm — Bambu lets the user shrink to 0 in two
        # clicks if they don't want it, and the cost of a too-small
        # brim (lifted corner, failed print) is much higher than the
        # cost of an unnecessary 5mm of waste plastic.
        _ = longest_mm  # unused for now; kept on signature for symmetry
        base = RecipeSettings(
            wall_loops=3,
            sparse_infill_density=15,
            sparse_infill_pattern="gyroid",
            top_shell_layers=4,
            bottom_shell_layers=4,
            brim_type="outer_only",
            brim_width=5.0,
            enable_support=False,
            spiral_mode=False,
        )

    # Filament setup. Each "active" filament slot needs one entry in
    # filament_settings_id + filament_colour. zebra/quarter both use 2
    # filaments (red + yellow); none uses 1.
    if color_split_mode in ("zebra", "quarter"):
        filament_settings = [FILAMENT_BAMBU_PLA, FILAMENT_BAMBU_PLA]
        filament_colours = [COLOR_RED_HEX, COLOR_YELLOW_HEX]
    else:
        filament_settings = [FILAMENT_BAMBU_PLA]
        filament_colours = [COLOR_RED_HEX]

    # RecipeSettings is frozen; rebuild with the filament fields.
    return RecipeSettings(
        printer_settings_id=base.printer_settings_id,
        process_settings_id=base.process_settings_id,
        layer_height=base.layer_height,
        wall_loops=base.wall_loops,
        top_shell_layers=base.top_shell_layers,
        bottom_shell_layers=base.bottom_shell_layers,
        sparse_infill_density=base.sparse_infill_density,
        sparse_infill_pattern=base.sparse_infill_pattern,
        brim_type=base.brim_type,
        brim_width=base.brim_width,
        enable_support=base.enable_support,
        spiral_mode=base.spiral_mode,
        filament_settings_id=filament_settings,
        filament_colour=filament_colours,
    )


def filament_index_for_color(color_token: str) -> int:
    """Map an STL filename color token (from ops/export_stl.py) to a
    1-based filament index. red -> 1, yellow -> 2. Default 1 for any
    unknown / un-tokenized mesh."""
    if color_token.startswith("red"):
        return 1
    if color_token.startswith("yellow"):
        return 2
    return 1
