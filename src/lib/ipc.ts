import { invoke } from "@tauri-apps/api/core";

export function invokeSidecar<T = unknown>(
    method: string,
    params: Record<string, unknown> = {}
): Promise<T> {
    return invoke<T>("invoke_sidecar", { method, params });
}
