import { createContext, useContext, useReducer } from "react";
import type { Dispatch, ReactNode } from "react";
import type { Edit, Sanity } from "./types";
import type { ObjectType, ColorSplitMode } from "./edits";

export interface ProjectState {
    name: string;
    prompt: string;
    previewTaskId: string | null;
    selectedGlbPath: string | null;
    edits: Edit[];
    lastSanity: Sanity | null;
    // Carried from the Editor so the Export screen can pick the shape-aware
    // slicer recipe and the STL color-split mode (not derivable from edits[]
    // alone — flat_part vs solid_decorative is indistinguishable there).
    objectType: ObjectType;
    colorSplitMode: ColorSplitMode;
    editApplied: boolean;
    /** .3mf written during apply_chain (while Blender session was live).
     *  Null if pre-bake failed or no Apply has run. Export uses this to
     *  skip the fresh-connect step that fails after session_scope closes. */
    prebaked3mfPath: string | null;
}

export const INITIAL_STATE: ProjectState = {
    name: "",
    prompt: "",
    previewTaskId: null,
    selectedGlbPath: null,
    edits: [],
    lastSanity: null,
    objectType: "vase",
    colorSplitMode: "none",
    editApplied: false,
    prebaked3mfPath: null,
};

export type ProjectAction =
    | { type: "SET_NAME"; name: string }
    | { type: "SET_PROMPT"; prompt: string }
    | { type: "SET_PREVIEW_TASK"; previewTaskId: string }
    | { type: "SET_GLB_PATH"; selectedGlbPath: string }
    | { type: "SET_EDITS"; edits: Edit[] }
    | { type: "SET_SANITY"; lastSanity: Sanity }
    | { type: "SET_EDIT_META"; objectType: ObjectType; colorSplitMode: ColorSplitMode; prebaked3mfPath?: string | null }
    | { type: "RESET" };

export function projectReducer(state: ProjectState, action: ProjectAction): ProjectState {
    switch (action.type) {
        case "SET_NAME":
            return { ...state, name: action.name };
        case "SET_PROMPT":
            return { ...state, prompt: action.prompt };
        case "SET_PREVIEW_TASK":
            return { ...state, previewTaskId: action.previewTaskId };
        case "SET_GLB_PATH":
            return { ...state, selectedGlbPath: action.selectedGlbPath };
        case "SET_EDITS":
            return { ...state, edits: action.edits };
        case "SET_SANITY":
            return { ...state, lastSanity: action.lastSanity };
        case "SET_EDIT_META":
            return {
                ...state,
                objectType: action.objectType,
                colorSplitMode: action.colorSplitMode,
                editApplied: true,
                prebaked3mfPath: action.prebaked3mfPath ?? null,
            };
        case "RESET":
            return { ...INITIAL_STATE };
        default:
            return state;
    }
}

const ProjectStateCtx = createContext<ProjectState>(INITIAL_STATE);
const ProjectDispatchCtx = createContext<Dispatch<ProjectAction>>(() => {});

export function ProjectProvider({ children }: { children: ReactNode }) {
    const [state, dispatch] = useReducer(projectReducer, INITIAL_STATE);
    return (
        <ProjectStateCtx.Provider value={state}>
            <ProjectDispatchCtx.Provider value={dispatch}>
                {children}
            </ProjectDispatchCtx.Provider>
        </ProjectStateCtx.Provider>
    );
}

export function useProjectState(): ProjectState {
    return useContext(ProjectStateCtx);
}

export function useProjectDispatch(): Dispatch<ProjectAction> {
    return useContext(ProjectDispatchCtx);
}
