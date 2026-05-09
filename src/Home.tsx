import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { invokeSidecar } from "./lib/ipc";

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
            <h1>Conjure3D v0.0.1</h1>
            <p>{sidecarStatus}</p>
            <button onClick={() => navigate("/new-project")}>New Project</button>
        </div>
    );
}
