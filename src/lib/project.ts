/**
 * Phase H Issue #26 — pure (de)serialization between the in-memory Editor
 * `ProjectState` and the on-disk `<slug>.conjure3d.json` (`ConjureProject`).
 *
 * Pure and side-effect-free: file IO + artifact copying live in the sidecar
 * (`sidecar/project.py`). These functions only shape the JSON so they can be
 * unit-tested without the app running. The error-code strings match the
 * sidecar's `project.ERROR_CODES` so the Editor branches on one contract.
 *
 * Forward-compat: `deserializeProject` ignores unknown extra fields rather
 * than rejecting them, so a newer file opened by an older build degrades
 * gracefully (version bump is the explicit break, handled separately).
 */
import {
    PROJECT_SCHEMA_VERSION,
    type ConjureProject,
    type Edit,
    type ProjectArtifacts,
} from "./types";
import type { ProjectState } from "./projectState";

export type ProjectErrorCode =
    | "SCHEMA_VERSION_MISMATCH"
    | "PROJECT_FILE_INVALID";

const COLOR_SPLIT = "color_split";

function colorSplitMode(edits: Edit[]): string {
    const cs = edits.find((e) => e.type === COLOR_SPLIT);
    const mode = cs?.["mode"];
    return typeof mode === "string" ? mode : "none";
}

/** Editor state → on-disk schema. `artifacts` defaults to the empty
 *  pre-export state (valid — only the slicer cares about STL presence). */
export function serializeProject(
    state: ProjectState,
    artifacts: ProjectArtifacts = { preview_glb: null, stl_paths: [] },
): ConjureProject {
    return {
        version: PROJECT_SCHEMA_VERSION,
        name: state.name,
        prompt: state.prompt,
        preview_task_id: state.previewTaskId,
        source_glb: state.selectedGlbPath,
        edits: state.edits,
        color_split_mode: colorSplitMode(state.edits),
        last_sanity: state.lastSanity,
        artifacts,
    };
}

const REQUIRED_FIELDS = [
    "version",
    "name",
    "prompt",
    "preview_task_id",
    "source_glb",
    "edits",
    "color_split_mode",
] as const;

export interface DeserializeResult {
    state?: ProjectState;
    project?: ConjureProject;
    errorCode?: ProjectErrorCode;
    message?: string;
}

/** On-disk schema → Editor state. Never throws; returns `errorCode` so the
 *  caller branches like the sidecar contract (mismatch → user prompt). */
export function deserializeProject(raw: unknown): DeserializeResult {
    if (typeof raw !== "object" || raw === null) {
        return { errorCode: "PROJECT_FILE_INVALID", message: "not an object" };
    }
    const doc = raw as Record<string, unknown>;

    if (doc.version !== PROJECT_SCHEMA_VERSION) {
        return {
            errorCode: "SCHEMA_VERSION_MISMATCH",
            message: `expected schema version ${PROJECT_SCHEMA_VERSION}, got ${String(
                doc.version,
            )}`,
        };
    }
    const missing = REQUIRED_FIELDS.filter((f) => !(f in doc));
    if (missing.length > 0) {
        return {
            errorCode: "PROJECT_FILE_INVALID",
            message: `missing required field(s): ${missing.join(", ")}`,
        };
    }

    const project = doc as unknown as ConjureProject;
    const state: ProjectState = {
        name: String(doc.name),
        prompt: String(doc.prompt),
        previewTaskId: (doc.preview_task_id as string | null) ?? null,
        selectedGlbPath: (doc.source_glb as string | null) ?? null,
        edits: (doc.edits as Edit[]) ?? [],
        lastSanity: (doc.last_sanity as ProjectState["lastSanity"]) ?? null,
        objectType: (doc.object_type as ProjectState["objectType"]) ?? "vase",
        colorSplitMode:
            (doc.color_split_mode as ProjectState["colorSplitMode"]) ?? "none",
        editApplied: Boolean((doc.edits as Edit[] | undefined)?.length),
    };
    return { state, project };
}
