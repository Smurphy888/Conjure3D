import { describe, it, expect } from "vitest";
import { serializeProject, deserializeProject } from "./project";
import { PROJECT_SCHEMA_VERSION } from "./types";
import type { ProjectState } from "./projectState";

const state: ProjectState = {
    name: "Mom's Vase",
    prompt: "a stylized vase",
    previewTaskId: "task-123",
    selectedGlbPath: "/tmp/src.glb",
    edits: [
        { type: "scale_to_longest", target_mm: 80 },
        { type: "color_split", mode: "zebra" },
    ],
    lastSanity: null,
    objectType: "vase",
    colorSplitMode: "zebra",
    bisectInChain: false,
    editApplied: true,
    prebaked3mfPath: null,
};

describe("serializeProject", () => {
    it("stamps the current schema version", () => {
        expect(serializeProject(state).version).toBe(PROJECT_SCHEMA_VERSION);
        expect(PROJECT_SCHEMA_VERSION).toBe(1);
    });

    it("maps Editor state field names to the on-disk schema", () => {
        const p = serializeProject(state);
        expect(p.preview_task_id).toBe("task-123");
        expect(p.source_glb).toBe("/tmp/src.glb");
        expect(p.edits).toHaveLength(2);
    });

    it("derives color_split_mode from the color_split edit", () => {
        expect(serializeProject(state).color_split_mode).toBe("zebra");
    });

    it("defaults color_split_mode to none when no split edit", () => {
        const noSplit = { ...state, edits: [{ type: "decimate", target_faces: 50000 }] };
        expect(serializeProject(noSplit).color_split_mode).toBe("none");
    });

    it("defaults artifacts to the empty pre-export state", () => {
        const p = serializeProject(state);
        expect(p.artifacts).toEqual({ preview_glb: null, stl_paths: [] });
    });
});

describe("deserializeProject", () => {
    it("round-trips a serialized project back to Editor state", () => {
        const onDisk = serializeProject(state, {
            preview_glb: "preview.glb",
            stl_paths: ["v_red.stl"],
        });
        const r = deserializeProject(JSON.parse(JSON.stringify(onDisk)));
        expect(r.errorCode).toBeUndefined();
        expect(r.state).toEqual(state);
        expect(r.project?.artifacts.stl_paths).toEqual(["v_red.stl"]);
    });

    it("rejects a version mismatch with SCHEMA_VERSION_MISMATCH", () => {
        const r = deserializeProject({ ...serializeProject(state), version: 99 });
        expect(r.errorCode).toBe("SCHEMA_VERSION_MISMATCH");
        expect(r.state).toBeUndefined();
    });

    it("rejects a missing required field with PROJECT_FILE_INVALID", () => {
        const bad = serializeProject(state) as unknown as Record<string, unknown>;
        delete bad.prompt;
        const r = deserializeProject(bad);
        expect(r.errorCode).toBe("PROJECT_FILE_INVALID");
        expect(r.message).toContain("prompt");
    });

    it("rejects non-objects", () => {
        expect(deserializeProject(null).errorCode).toBe("PROJECT_FILE_INVALID");
        expect(deserializeProject("nope").errorCode).toBe("PROJECT_FILE_INVALID");
    });

    it("tolerates unknown extra fields (forward compat)", () => {
        const withExtra = {
            ...serializeProject(state),
            future_field: { anything: true },
        };
        const r = deserializeProject(withExtra);
        expect(r.errorCode).toBeUndefined();
        expect(r.state?.name).toBe("Mom's Vase");
    });
});
