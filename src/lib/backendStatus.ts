/**
 * Maps the sidecar's LLM backend metadata (from `llm.backend_info`) onto a
 * user-facing description. The whole point is to STOP silently degrading:
 * when the real AI model can't load, the AI Editor was still labelled
 * "Powered by: mock-keyword-router" — jargon nobody reads — so users assumed
 * they were talking to real AI and were baffled when free-form requests were
 * ignored. This surfaces the truth in plain language.
 *
 * `backend` is the active backend's name (e.g. "mock-keyword-router" or a
 * llama.cpp / cloud backend name). `install_status` is WHY we're on whatever
 * backend we're on — one of:
 *   "installed"            — real local model loaded; not degraded
 *   "not_attempted"        — startup probe hasn't run yet
 *   "library_unavailable"  — AI engine missing from this build
 *   "model_missing"        — model file not downloaded yet
 *   "load_failed: <why>"   — engine + file present, but loading crashed
 *                            (e.g. CPU lacks the required instructions)
 */

export interface BackendStatus {
    /** True when the user is NOT talking to a real AI model. */
    degraded: boolean;
    /** Short label for the "mode" indicator. */
    label: string;
    /** Plain-language explanation + what to do, or null when not degraded. */
    message: string | null;
}

const MOCK_NAMES = new Set(["mock-keyword-router", "MockBackend"]);

export function describeBackend(
    backend: string | undefined,
    installStatus: string | undefined
): BackendStatus {
    const status = installStatus ?? "not_attempted";
    const onMock = backend ? MOCK_NAMES.has(backend) : true;

    // Real model loaded and active — no notice.
    if (status === "installed" && !onMock) {
        return { degraded: false, label: "AI model", message: null };
    }

    // Probe hasn't reported yet — stay quiet rather than flash a scary banner
    // during the first render.
    if (status === "not_attempted") {
        return { degraded: false, label: "Starting…", message: null };
    }

    const basicMode =
        "You're in basic keyword mode — free-form requests like " +
        "“split this in half” won't be understood. Use the supported keywords " +
        "(size in mm, “zebra”/“quarter” colours, “vase”, “flat bottom”, " +
        "“less detail”), or build the plan by hand with the “+ Add op” menu.";

    if (status.startsWith("load_failed")) {
        return {
            degraded: true,
            label: "Basic keyword mode",
            message:
                "The local AI model couldn't load on this PC — its engine needs " +
                "newer CPU instructions than this processor supports. " +
                basicMode,
        };
    }
    if (status === "model_missing") {
        return {
            degraded: true,
            label: "Basic keyword mode",
            message:
                "The local AI model hasn't been downloaded yet. " + basicMode,
        };
    }
    if (status === "library_unavailable") {
        return {
            degraded: true,
            label: "Basic keyword mode",
            message:
                "The local AI engine isn't available in this build. " + basicMode,
        };
    }

    // Unknown status but on the mock — still degraded.
    if (onMock) {
        return { degraded: true, label: "Basic keyword mode", message: basicMode };
    }
    return { degraded: false, label: backend ?? "AI", message: null };
}
