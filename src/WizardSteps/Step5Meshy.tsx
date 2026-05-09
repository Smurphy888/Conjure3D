import { useEffect, useState } from "react";
import { invokeSidecar } from "../lib/ipc";

interface Props {
    onComplete: () => void;
}

export function Step5Meshy({ onComplete }: Props) {
    const [key, setKey] = useState("");
    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState(false);
    const [alreadySet, setAlreadySet] = useState<boolean | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        invokeSidecar<{ set: boolean }>("system.has_meshy_key")
            .then((r) => setAlreadySet(r.set))
            .catch(() => setAlreadySet(false));
    }, []);

    async function saveKey() {
        if (!key.trim()) return;
        setSaving(true);
        setError(null);
        try {
            await invokeSidecar("system.set_meshy_key", { key: key.trim() });
            setSaved(true);
            setAlreadySet(true);
        } catch (e) {
            setError(`Failed to save key: ${String(e)}`);
        } finally {
            setSaving(false);
        }
    }

    const canContinue = saved || alreadySet === true;

    return (
        <div>
            <h2>Step 5: Meshy API Key</h2>
            <p>
                Conjure3D uses{" "}
                <strong>Meshy</strong> to generate 3D models from text.
                Your key is stored in Windows Credential Manager and never leaves your machine.
            </p>
            {alreadySet === true && !saved && (
                <p style={{ color: "green" }}>A Meshy API key is already saved.</p>
            )}
            {alreadySet === false && (
                <p style={{ color: "orange" }}>No Meshy API key found. Enter it below.</p>
            )}
            <div style={{ marginTop: "0.5rem" }}>
                <input
                    type="password"
                    placeholder="Paste your Meshy API key here"
                    value={key}
                    onChange={(e) => setKey(e.target.value)}
                    style={{ width: "100%", marginBottom: "0.5rem" }}
                    disabled={saving}
                />
                <button onClick={saveKey} disabled={saving || !key.trim()}>
                    {saving ? "Saving..." : "Save key"}
                </button>
            </div>
            {saved && <p style={{ color: "green" }}>Key saved to Windows Credential Manager.</p>}
            {error && <p style={{ color: "red" }}>{error}</p>}
            <div style={{ marginTop: "0.5rem" }}>
                {canContinue && (
                    <button onClick={onComplete}>Continue</button>
                )}
            </div>
        </div>
    );
}
