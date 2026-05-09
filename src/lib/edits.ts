import type { Edit } from "./types";

export type ObjectType = "vase" | "solid_decorative" | "flat_part";
export type ColorSplitMode = "none" | "zebra" | "quarter";

export interface EditorParams {
    target_height_mm: number;
    object_type: ObjectType;
    flat_bottom: boolean;
    decimate_target_faces: number;
    color_split_mode: ColorSplitMode;
    color_split_count: number;
}

export const DEFAULT_PARAMS: EditorParams = {
    target_height_mm: 80,
    object_type: "vase",
    flat_bottom: true,
    decimate_target_faces: 50000,
    color_split_mode: "none",
    color_split_count: 8,
};

/** Build the ordered edit chain from Editor params. Auto-clean order is fixed. */
export function buildEdits(params: EditorParams): Edit[] {
    const edits: Edit[] = [
        { type: "scale_to_longest", target_mm: params.target_height_mm },
        { type: "voxel_remesh", voxel_mm: 0.8 },
        { type: "keep_largest" },
        { type: "recenter_xy" },
        ...(params.flat_bottom ? [{ type: "flat_bottom", cut_mm: 1 }] : []),
        { type: "fix_normals" },
        { type: "decimate", target_faces: params.decimate_target_faces },
    ];

    if (params.object_type === "vase") {
        edits.push({ type: "open_top", cut_mm: 2 });
        edits.push({ type: "bridge_top_loops" });
    }

    if (params.color_split_mode !== "none") {
        edits.push({
            type: "color_split",
            mode: params.color_split_mode,
            count: params.color_split_count,
            axis: "z",
            colors: ["red", "yellow"],
        });
    }

    return edits;
}

/** Returns true when the color split warning should be shown. */
export function shouldWarnColorSplit(params: EditorParams): boolean {
    return params.color_split_mode !== "none" && params.object_type !== "vase";
}
