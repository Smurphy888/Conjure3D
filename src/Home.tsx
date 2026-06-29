import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { emit } from "@tauri-apps/api/event";
import { invokeSidecar } from "./lib/ipc";
import { AboutDialog } from "./components/AboutDialog";
import { appVersion } from "./lib/about";

const PROVIDER_LABELS: Record<string, string> = {
    meshy: "Meshy",
    tripo: "Tripo AI",
};

export function Home() {
    const [sidecarError, setSidecarError] = useState<string | null>(null);
    const [provider, setProvider] = useState<string | null>(null);
    const navigate = useNavigate();

    useEffect(() => {
        invokeSidecar<{ ok: boolean; msg: string }>("system.ping")
            .then(() => setSidecarError(null))
            .catch((err) => setSidecarError(`Sidecar error: ${String(err)}`));
        invokeSidecar<{ provider: string }>("system.get_generation_provider")
            .then((r) => setProvider(r.provider))
            .catch(() => {});
    }, []);

    return (
        <div className="container">
            <h1>Conjure3D v{appVersion()}</h1>
            {sidecarError && (
                <p style={{ color: "#ff6b6b", fontSize: "0.85rem" }}>{sidecarError}</p>
            )}
            <button onClick={() => navigate("/new-project")}>New Project</button>
            {provider !== null && (
                <p style={{ fontSize: "0.82rem", color: "#aaa", marginTop: "1rem" }}>
                    AI provider: {PROVIDER_LABELS[provider] ?? provider}{" "}
                    <button
                        style={{
                            fontSize: "0.75rem",
                            padding: "0.1rem 0.5rem",
                            cursor: "pointer",
                            background: "transparent",
                            border: "1px solid #555",
                            borderRadius: 4,
                            color: "#ccc",
                        }}
                        onClick={() => emit("run-wizard", { startAt: 4 })}
                    >
                        Change
                    </button>
                </p>
            )}
            <div style={{ marginTop: "1.25rem" }}>
                <AboutDialog />
            </div>
        </div>
    );
}
