import { useState } from "react";
import { invokeSidecar } from "../lib/ipc";

interface TestResult {
    connected: boolean;
    error?: string;
}

interface Props {
    onComplete: () => void;
}

export function Step3Socket({ onComplete }: Props) {
    const [result, setResult] = useState<TestResult | null>(null);
    const [testing, setTesting] = useState(false);

    function test() {
        setTesting(true);
        invokeSidecar<TestResult>("wizard.test_socket")
            .then(setResult)
            .catch(() => setResult({ connected: false, error: "Failed to call sidecar" }))
            .finally(() => setTesting(false));
    }

    return (
        <div>
            <h2>Step 3: BlenderMCP Connection</h2>
            <p>
                In Blender, open the sidebar (N-key), click the <strong>BlenderMCP</strong> tab,
                then click <strong>Connect to Claude</strong>. Then test the connection below.
            </p>
            {result?.connected && (
                <p style={{ color: "green" }}>Connected! BlenderMCP is running.</p>
            )}
            {result && !result.connected && (
                <p style={{ color: "red" }}>{result.error}</p>
            )}
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem" }}>
                <button onClick={test} disabled={testing}>
                    {testing ? "Testing..." : "Test connection"}
                </button>
                {result?.connected && (
                    <button onClick={() => onComplete()}>Continue</button>
                )}
            </div>
        </div>
    );
}
