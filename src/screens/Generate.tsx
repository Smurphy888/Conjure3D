import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { invokeSidecar } from "../lib/ipc";
import { useProjectState, useProjectDispatch } from "../lib/projectState";

type PollResult = {
    status: "PROCESSING" | "SUCCEEDED" | "FAILED";
    progress: number;
    model_urls?: { glb: string };
};

export function Generate() {
    const { prompt } = useProjectState();
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
                        dispatch({ type: "SET_GLB_PATH", selectedGlbPath: r.model_urls.glb });
                        navigate("/preview-pick");
                        return;
                    }
                    if (r.status === "FAILED") {
                        setError("Meshy generation failed.");
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
            <p>Generating your 3D model via Meshy…</p>
            {taskId && <p>Task: {taskId}</p>}
            <p>Progress: {progress}%</p>
            <button onClick={() => navigate("/new-project")}>Cancel</button>
        </div>
    );
}
