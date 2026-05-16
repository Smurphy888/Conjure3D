import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { invokeSidecar } from "./lib/ipc";
import { AboutDialog } from "./components/AboutDialog";
import { appVersion } from "./lib/about";

export function Home() {
    const [sidecarStatus, setSidecarStatus] = useState("loading...");
    const navigate = useNavigate();

    useEffect(() => {
        invokeSidecar<{ ok: boolean; msg: string }>("system.ping")
            .then((result) => setSidecarStatus(`Sidecar: ${result.msg}`))
            .catch((err) => setSidecarStatus(`Sidecar error: ${String(err)}`));
    }, []);

    return (
        <div className="container">
            <h1>Conjure3D v{appVersion()}</h1>
            <p>{sidecarStatus}</p>
            <button onClick={() => navigate("/new-project")}>New Project</button>
            <div style={{ marginTop: "1.25rem" }}>
                <AboutDialog />
            </div>
        </div>
    );
}
