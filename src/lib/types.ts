/** Sanity check result from edit.apply_chain. */
export interface Sanity {
    manifold: boolean;
    single_component: boolean;
    normals_outward: boolean;
    longest_dim_under_limit: boolean;
    dims_mm: [number, number, number];
}

/** One edit operation in the chain. */
export interface Edit {
    type: string;
    [key: string]: unknown;
}

/** Response from edit.apply_chain. */
export interface EditChainResult {
    preview_glb: string;
    sanity: Sanity;
    stl_paths: string[];
    errors?: string[];
}

/** Current persisted-project schema version (Phase H Issue #26). The
 *  sidecar mirrors this as orchestrator.PROJECT_SCHEMA_VERSION. */
export const PROJECT_SCHEMA_VERSION = 1;

/** Artifact filenames, relative to the sibling `<slug>.conjure3d/` folder
 *  the copies live in (the byte-identical record). */
export interface ProjectArtifacts {
    preview_glb: string | null;
    stl_paths: string[];
}

/** `<slug>.conjure3d.json` on disk. Canonical schema; the sidecar
 *  (sidecar/project.py + orchestrator.py) mirrors the version + the fields
 *  it validates. Unknown extra fields must be tolerated on load. */
export interface ConjureProject {
    version: typeof PROJECT_SCHEMA_VERSION;
    name: string;
    prompt: string;
    preview_task_id: string | null;
    source_glb: string | null;
    edits: Edit[];
    color_split_mode: string;
    last_sanity: Sanity | null;
    artifacts: ProjectArtifacts;
}
