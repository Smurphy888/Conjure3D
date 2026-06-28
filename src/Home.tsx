import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { invokeSidecar } from "./lib/ipc";
import { AboutDialog } from "./components/AboutDialog";
import { appVersion } from "./lib/about";

export function Home() {
    const [sidecarError, setSidecarError] = useState<string | null>(null);
    const navigate = useNavigate();

    useEffect(() => {
        invokeSidecar<{ ok: boolean; msg: string }>("system.ping")
            .then(() => setSidecarError(null))
            .catch((err) => setSidecarError(`Sidecar error: ${String(err)}`));
    }, []);

    return (
        <div className="container">
            <h1>Conjure3D v{appVersion()}</h1>
            {sidecarError && (
                <p style={{ color: "#ff6b6b", fontSize: "0.85rem" }}>{sidecarError}</p>
            )}
            <button onClick={() => navigate("/new-project")}>New Project</button>
            <div style={{ marginTop: "1.25rem" }}>
                <AboutDialog />
            </div>
        </div>
    );
}
