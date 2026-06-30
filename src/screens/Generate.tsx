import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { invokeSidecar } from "../lib/ipc";
import { useProjectState, useProjectDispatch } from "../lib/projectState";

type PollResult = {
    status: "PROCESSING" | "SUCCEEDED" | "FAILED";
    progress: number;
    model_urls?: { glb: string };
    task_error?: string;
};

const PROVIDER_LABELS: Record<string, string> = {
    meshy: "Meshy",
    tripo: "Tripo AI",
};

function phaseLabel(progress: number): string {
    if (progress < 5) return "Starting up…";
    if (progress < 75) return "Generating 3D mesh…";
    return "Finalizing…";
}

export function Generate() {
    const { prompt, name } = useProjectState();
    const dispatch = useProjectDispatch();
    const navigate = useNavigate();
    const [taskId, setTaskId] = useState<string | null>(null);
    const [progress, setProgress] = useState(0);
    const [error, setError] = useState<string | null>(null);
    const [providerLabel, setProviderLabel] = useState("AI service");

    useEffect(() => {
        let cancelled = false;

        async function run() {
            try {
                const prov = await invokeSidecar<{ provider: string }>("system.get_generation_provider");
                if (!cancelled) {
                    setProviderLabel(PROVIDER_LABELS[prov.provider] ?? prov.provider);
                }

                const gen = await invokeSidecar<{ task_id: string }>("model.generate_preview", { prompt });
                if (cancelled) return;
                setTaskId(gen.task_id);
                dispatch({ type: "SET_PREVIEW_TASK", previewTaskId: gen.task_id });

                while (!cancelled) {
                    await new Promise<void>((r) => setTimeout(r, 2000));
                    if (cancelled) break;
                    const r = await invokeSidecar<PollResult>("model.poll_task", { task_id: gen.task_id });
                    if (cancelled) break;
                    setProgress(r.progress);
                    if (r.status === "SUCCEEDED" && r.model_urls) {
                        let glb = r.model_urls.glb;
                        // Signed remote URLs expire and can't be rendered by the webview.
                        // Fetch to a local project dir; the provider module returns a
                        // local path directly for mock/offline cases (no http prefix).
                        if (/^https?:/i.test(glb)) {
                            const dl = await invokeSidecar<{ path: string }>(
                                "model.download_glb",
                                { url: glb, name }
                            );
                            if (cancelled) return;
                            glb = dl.path;
                        }
                        dispatch({ type: "SET_GLB_PATH", selectedGlbPath: glb });
                        navigate("/preview-pick");
                        return;
                    }
                    if (r.status === "FAILED") {
                        setError(r.task_error || "3D model generation failed.");
                        return;
                    }
                }
            } catch (e) {
                if (!cancelled) setError(String(e));
            }
        }

        run();
        return () => { cancelled = true; };
    }, []);

    if (error) {
        return (
            <div className="container">
                <h2>Generate</h2>
                <p style={{ color: "var(--danger)" }}>{error}</p>
                <button onClick={() => navigate("/new-project")}>Back</button>
            </div>
        );
    }

    return (
        <div className="container">
            <h2>Generate</h2>
            <p style={{ color: "var(--text-muted)" }}>
                {taskId ? `${phaseLabel(progress)} (via ${providerLabel})` : "Starting generation…"}
            </p>
            <div
                style={{
                    width: "min(420px, 80vw)",
                    height: 10,
                    border: "1px solid var(--border)",
                    borderRadius: 999,
                    overflow: "hidden",
                    background: "var(--surface)",
                    margin: "0.75rem 0",
                }}
            >
                <div
                    style={{
                        width: `${Math.max(4, progress)}%`,
                        height: "100%",
                        background: "var(--accent)",
                        transition: "width 0.4s ease",
                    }}
                />
            </div>
            <p style={{ fontSize: "0.9rem", color: "var(--text)" }}>{progress}%</p>
            {taskId && (
                <p style={{ fontSize: "0.75rem", color: "var(--text-faint)" }}>Task: {taskId}</p>
            )}
            <button onClick={() => navigate("/new-project")}>Cancel</button>
        </div>
    );
}
