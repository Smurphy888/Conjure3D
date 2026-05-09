import { createContext, useContext, useReducer } from "react";
import type { Dispatch, ReactNode } from "react";

export interface ProjectState {
    name: string;
    prompt: string;
    previewTaskId: string | null;
    selectedGlbPath: string | null;
    edits: unknown[];
}

export const INITIAL_STATE: ProjectState = {
    name: "",
    prompt: "",
    previewTaskId: null,
    selectedGlbPath: null,
    edits: [],
};

export type ProjectAction =
    | { type: "SET_NAME"; name: string }
    | { type: "SET_PROMPT"; prompt: string }
    | { type: "SET_PREVIEW_TASK"; previewTaskId: string }
    | { type: "SET_GLB_PATH"; selectedGlbPath: string }
    | { type: "SET_EDITS"; edits: unknown[] }
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
