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

export function Generate() {
    const { prompt, name } = useProjectState();
    const dispatch = useProjectDispatch();
    const navigate = useNavigate();
    const [taskId, setTaskId] = useState<string | null>(null);
    const [progress, setProgress] = useState(0);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;

        async function run() {
            try {
                const gen = await invokeSidecar<{ task_id: string }>("meshy.generate_preview", { prompt });
                if (cancelled) return;
                setTaskId(gen.task_id);
                dispatch({ type: "SET_PREVIEW_TASK", previewTaskId: gen.task_id });

                while (!cancelled) {
                    await new Promise<void>((r) => setTimeout(r, 2000));
                    if (cancelled) break;
                    const r = await invokeSidecar<PollResult>("meshy.poll_task", { task_id: gen.task_id });
                    if (cancelled) break;
                    setProgress(r.progress);
                    if (r.status === "SUCCEEDED" && r.model_urls) {
                        let glb = r.model_urls.glb;
                        // Real Meshy returns a signed S3 URL the webview can't
                        // render and that expires (~24h). Fetch it to a local
                        // project dir and use that path. Mock returns a local
                        // path already (no http) — passes through unchanged.
                        if (/^https?:/i.test(glb)) {
                            const dl = await invokeSidecar<{ path: string }>(
                                "meshy.download_glb",
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
                        // Surface Meshy's verbatim message; never auto-retry.
                        setError(r.task_error ? `Meshy: ${r.task_error}` : "Meshy generation failed.");
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
                <p style={{ color: "red" }}>{error}</p>
                <button onClick={() => navigate("/new-project")}>Back</button>
            </div>
        );
    }

    return (
        <div className="container">
            <h2>Generate</h2>
            <p>{taskId ? "Generating your 3D model via Meshy…" : "Starting generation…"}</p>
            <div
                style={{
                    width: "min(420px, 80vw)",
                    height: 14,
                    border: "1px solid #444",
                    borderRadius: 999,
                    overflow: "hidden",
                    background: "#1a1a1a",
                    margin: "0.75rem 0",
                }}
            >
                <div
                    style={{
                        width: `${Math.max(4, progress)}%`,
                        height: "100%",
                        background: "#a855f7",
                        transition: "width 0.4s ease",
                    }}
                />
            </div>
            <p style={{ fontSize: "0.9rem" }}>{progress}%</p>
            {taskId && (
                <p style={{ fontSize: "0.75rem", color: "#888" }}>Task: {taskId}</p>
            )}
            <button onClick={() => navigate("/new-project")}>Cancel</button>
        </div>
    );
}
