import { useEffect, useRef, useState } from "react";
import { invokeSidecar } from "../lib/ipc";
import type { Settings } from "../lib/settings";

interface DetectResult {
    found: boolean;
    path: string | null;
}

interface Props {
    onComplete: (updates?: Partial<Omit<Settings, "version" | "wizard">>) => void;
}

export function Step4Bambu({ onComplete }: Props) {
    const [result, setResult] = useState<DetectResult | null>(null);
    const [checking, setChecking] = useState(false);
    const [manualPath, setManualPath] = useState("");
    const inputRef = useRef<HTMLInputElement>(null);

    function detect() {
        setChecking(true);
        invokeSidecar<DetectResult>("wizard.detect_bambu")
            .then(setResult)
            .catch(() => setResult({ found: false, path: null }))
            .finally(() => setChecking(false));
    }

    useEffect(() => {
        detect();
    }, []);

    function handleContinue() {
        if (result?.found && result.path) {
            onComplete({ bambu_path: result.path });
        } else if (manualPath.trim()) {
            onComplete({ bambu_path: manualPath.trim() });
        }
    }

    const resolvedPath = result?.found ? result.path : manualPath.trim() || null;

    return (
        <div>
            <h2>Step 4: Bambu Studio</h2>
            <p>Conjure3D will launch Bambu Studio when you&apos;re ready to slice your model.</p>
            {checking && <p>Detecting Bambu Studio...</p>}
            {result && !checking && (
                result.found
                    ? <p style={{ color: "green" }}>Found: {result.path}</p>
                    : (
                        <div>
                            <p style={{ color: "orange" }}>
                                Bambu Studio not found at default location.
                                Paste the full path to bambu-studio.exe below.
                            </p>
                            <input
                                ref={inputRef}
                                type="text"
                                placeholder="C:\Program Files\Bambu Studio\bambu-studio.exe"
                                value={manualPath}
                                onChange={(e) => setManualPath(e.target.value)}
                                style={{ width: "100%", marginBottom: "0.5rem" }}
                            />
                        </div>
                    )
            )}
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem" }}>
                <button onClick={detect} disabled={checking}>Re-check</button>
                {resolvedPath && (
                    <button className="btn-primary" onClick={handleContinue}>Continue</button>
                )}
            </div>
        </div>
    );
}
