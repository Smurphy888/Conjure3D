import { describe, it, expect } from "vitest";
import { buildEdits, shouldWarnColorSplit, DEFAULT_PARAMS, type EditorParams } from "./edits";

const base: EditorParams = { ...DEFAULT_PARAMS };

describe("buildEdits — fixed auto-clean order", () => {
    it("always starts with scale_to_longest", () => {
        const edits = buildEdits(base);
        expect(edits[0].type).toBe("scale_to_longest");
    });

    it("voxel_remesh is second (must follow scale)", () => {
        const edits = buildEdits(base);
        expect(edits[1].type).toBe("voxel_remesh");
    });

    it("decimate present in every chain", () => {
        const edits = buildEdits(base);
        expect(edits.some((e) => e.type === "decimate")).toBe(true);
    });

    it("vase includes open_top and bridge_top_loops", () => {
        const edits = buildEdits({ ...base, object_type: "vase" });
        const types = edits.map((e) => e.type);
        expect(types).toContain("open_top");
        expect(types).toContain("bridge_top_loops");
    });

    it("solid_decorative skips open_top and bridge_top_loops", () => {
        const edits = buildEdits({ ...base, object_type: "solid_decorative" });
        const types = edits.map((e) => e.type);
        expect(types).not.toContain("open_top");
        expect(types).not.toContain("bridge_top_loops");
    });

    it("flat_part skips open_top and bridge_top_loops", () => {
        const edits = buildEdits({ ...base, object_type: "flat_part" });
        const types = edits.map((e) => e.type);
        expect(types).not.toContain("open_top");
        expect(types).not.toContain("bridge_top_loops");
    });

    it("flat_bottom false removes flat_bottom edit", () => {
        const edits = buildEdits({ ...base, flat_bottom: false });
        expect(edits.some((e) => e.type === "flat_bottom")).toBe(false);
    });

    it("flat_bottom true includes flat_bottom edit", () => {
        const edits = buildEdits({ ...base, flat_bottom: true });
        expect(edits.some((e) => e.type === "flat_bottom")).toBe(true);
    });

    it("color_split_mode none produces no color_split edit", () => {
        const edits = buildEdits({ ...base, color_split_mode: "none" });
        expect(edits.some((e) => e.type === "color_split")).toBe(false);
    });

    it("color_split_mode zebra appends color_split as last edit", () => {
        const edits = buildEdits({ ...base, color_split_mode: "zebra", color_split_count: 4 });
        const last = edits[edits.length - 1];
        expect(last.type).toBe("color_split");
        expect(last.mode).toBe("zebra");
        expect(last.count).toBe(4);
    });

    it("color_split_mode quarter appends color_split as last edit", () => {
        const edits = buildEdits({ ...base, color_split_mode: "quarter" });
        const last = edits[edits.length - 1];
        expect(last.type).toBe("color_split");
        expect(last.mode).toBe("quarter");
    });

    it("scale_to_longest uses target_height_mm from params", () => {
        const edits = buildEdits({ ...base, target_height_mm: 120 });
        expect(edits[0].target_mm).toBe(120);
    });

    it("decimate uses decimate_target_faces from params", () => {
        const edits = buildEdits({ ...base, decimate_target_faces: 30000 });
        const dec = edits.find((e) => e.type === "decimate")!;
        expect(dec.target_faces).toBe(30000);
    });
});

describe("shouldWarnColorSplit", () => {
    it("no warning when mode is none", () => {
        expect(shouldWarnColorSplit({ ...base, color_split_mode: "none", object_type: "solid_decorative" })).toBe(false);
    });

    it("no warning for vase + zebra", () => {
        expect(shouldWarnColorSplit({ ...base, color_split_mode: "zebra", object_type: "vase" })).toBe(false);
    });

    it("warning for solid_decorative + zebra", () => {
        expect(shouldWarnColorSplit({ ...base, color_split_mode: "zebra", object_type: "solid_decorative" })).toBe(true);
    });

    it("warning for flat_part + quarter", () => {
        expect(shouldWarnColorSplit({ ...base, color_split_mode: "quarter", object_type: "flat_part" })).toBe(true);
    });
});
