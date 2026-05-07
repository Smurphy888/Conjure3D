import { useEffect, useState } from "react";
import { invokeSidecar } from "./lib/ipc";

function App() {
    const [sidecarStatus, setSidecarStatus] = useState("loading...");

    useEffect(() => {
        invokeSidecar<{ ok: boolean; msg: string }>("system.ping")
            .then((result) => setSidecarStatus(`Sidecar: ${result.msg}`))
            .catch((err) => setSidecarStatus(`Sidecar error: ${String(err)}`));
    }, []);

    return (
        <div className="container">
            <h1>Conjure3D v0.0.1</h1>
            <p>{sidecarStatus}</p>
        </div>
    );
}

export default App;
