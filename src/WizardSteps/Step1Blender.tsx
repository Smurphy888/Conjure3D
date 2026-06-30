import { useEffect, useState } from "react";
import { invokeSidecar } from "../lib/ipc";

interface DetectResult {
    found: boolean;
    path: string | null;
    version: string | null;
}

interface Props {
    onComplete: () => void;
}

function isVersionOk(version: string | null): boolean {
    if (!version) return false;
    const parts = version.split(".").map(Number);
    const [major = 0, minor = 0] = parts;
    return major > 4 || (major === 4 && minor >= 2);
}

export function Step1Blender({ onComplete }: Props) {
    const [result, setResult] = useState<DetectResult | null>(null);
    const [checking, setChecking] = useState(false);

    function check() {
        setChecking(true);
        invokeSidecar<DetectResult>("wizard.detect_blender")
            .then(setResult)
            .catch(() => setResult({ found: false, path: null, version: null }))
            .finally(() => setChecking(false));
    }

    useEffect(() => {
        check();
    }, []);

    const versionOk = result ? isVersionOk(result.version) : false;
    const showDownload = result && (!result.found || !versionOk);

    function openDownload() {
        invokeSidecar("system.open_url", { url: "https://www.blender.org/download/lts/" });
    }

    return (
        <div>
            <h2>Step 1: Blender</h2>
            <p>Conjure3D requires Blender 4.2 LTS or later.</p>
            {checking && <p>Checking for Blender...</p>}
            {result && !checking && (
                versionOk
                    ? <p style={{ color: "green" }}>Found: {result.path} (v{result.version})</p>
                    : result.found
                        ? <p style={{ color: "orange" }}>Found v{result.version} — Blender 4.2+ required. Please upgrade.</p>
                        : <p style={{ color: "red" }}>Blender not found. Install Blender 4.2 LTS or later.</p>
            )}
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem" }}>
                <button onClick={check} disabled={checking}>Re-check</button>
                {showDownload && (
                    <button onClick={openDownload}>Download Blender LTS</button>
                )}
                {versionOk && (
                    <button className="btn-primary" onClick={() => onComplete()}>Continue</button>
                )}
            </div>
        </div>
    );
}
