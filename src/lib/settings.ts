import { invokeSidecar } from "./ipc";

export interface WizardState {
    step_blender: boolean;
    step_addon: boolean;
    step_socket: boolean;
    step_bambu: boolean;
    step_meshy: boolean;
}

export interface Settings {
    version: 1;
    wizard: WizardState;
    bambu_path: string | null;
}

const DEFAULT_WIZARD: WizardState = {
    step_blender: false,
    step_addon: false,
    step_socket: false,
    step_bambu: false,
    step_meshy: false,
};

export const DEFAULT_SETTINGS: Settings = {
    version: 1,
    wizard: { ...DEFAULT_WIZARD },
    bambu_path: null,
};

export function wizardComplete(s: Settings): boolean {
    const w = s.wizard;
    return w.step_blender && w.step_addon && w.step_socket && w.step_bambu && w.step_meshy;
}

export async function readSettings(): Promise<Settings> {
    return invokeSidecar<Settings>("settings.read");
}

export async function writeSettings(settings: Settings): Promise<void> {
    await invokeSidecar("settings.write", { settings });
}
