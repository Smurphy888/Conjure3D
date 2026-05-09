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
