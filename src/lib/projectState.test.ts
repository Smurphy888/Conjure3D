import { describe, it, expect } from "vitest";
import { projectReducer, INITIAL_STATE } from "./projectState";

describe("projectReducer", () => {
    it("SET_NAME updates name", () => {
        const s = projectReducer(INITIAL_STATE, { type: "SET_NAME", name: "My Model" });
        expect(s.name).toBe("My Model");
    });

    it("SET_PROMPT updates prompt", () => {
        const s = projectReducer(INITIAL_STATE, { type: "SET_PROMPT", prompt: "a dragon" });
        expect(s.prompt).toBe("a dragon");
    });

    it("SET_PREVIEW_TASK updates previewTaskId", () => {
        const s = projectReducer(INITIAL_STATE, { type: "SET_PREVIEW_TASK", previewTaskId: "task-123" });
        expect(s.previewTaskId).toBe("task-123");
    });

    it("SET_GLB_PATH updates selectedGlbPath", () => {
        const s = projectReducer(INITIAL_STATE, { type: "SET_GLB_PATH", selectedGlbPath: "/tmp/model.glb" });
        expect(s.selectedGlbPath).toBe("/tmp/model.glb");
    });

    it("SET_EDITS updates edits array", () => {
        const edits = [{ op: "scale", value: 2 }];
        const s = projectReducer(INITIAL_STATE, { type: "SET_EDITS", edits });
        expect(s.edits).toEqual(edits);
    });

    it("RESET returns initial state", () => {
        const dirty = projectReducer(INITIAL_STATE, { type: "SET_NAME", name: "dirty" });
        const s = projectReducer(dirty, { type: "RESET" });
        expect(s).toEqual(INITIAL_STATE);
    });

    it("unknown action returns state unchanged", () => {
        // @ts-expect-error testing unknown action
        const s = projectReducer(INITIAL_STATE, { type: "UNKNOWN" });
        expect(s).toEqual(INITIAL_STATE);
    });
});
