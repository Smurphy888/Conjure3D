import { useEffect, useState } from "react";
import { invokeSidecar } from "../lib/ipc";

type Provider = "meshy" | "tripo";

interface Props {
    onComplete: (updates?: { generation_provider: Provider }) => void;
    currentProvider?: Provider;
}

const PROVIDER_LABELS: Record<Provider, string> = {
    meshy: "Meshy",
    tripo: "Tripo AI",
};

const KEY_PLACEHOLDER: Record<Provider, string> = {
    meshy: "Paste your Meshy API key",
    tripo: "Paste your Tripo AI key (starts with tsk_)",
};

const HAS_KEY_CMD: Record<Provider, string> = {
    meshy: "system.has_meshy_key",
    tripo: "system.has_tripo_key",
};

const SET_KEY_CMD: Record<Provider, string> = {
    meshy: "system.set_meshy_key",
    tripo: "system.set_tripo_key",
};

export function Step5Meshy({ onComplete, currentProvider = "meshy" }: Props) {
    const [provider, setProvider] = useState<Provider>(currentProvider);
    const [key, setKey] = useState("");
    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState(false);
    const [keyAlreadySet, setKeyAlreadySet] = useState<boolean | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        setKeyAlreadySet(null);
        setSaved(false);
        setKey("");
        setError(null);
        invokeSidecar<{ set: boolean }>(HAS_KEY_CMD[provider])
            .then((r) => setKeyAlreadySet(r.set))
            .catch(() => setKeyAlreadySet(false));
    }, [provider]);

    async function saveKey() {
        if (!key.trim()) return;
        setSaving(true);
        setError(null);
        try {
            await invokeSidecar(SET_KEY_CMD[provider], { key: key.trim() });
            setSaved(true);
            setKeyAlreadySet(true);
        } catch (e) {
            setError(`Failed to save key: ${String(e)}`);
        } finally {
            setSaving(false);
        }
    }

    const canContinue = saved || keyAlreadySet === true;
    const label = PROVIDER_LABELS[provider];

    return (
        <div>
            <h2>Step 5: 3D Model Generation</h2>
            <p>Choose which AI service generates your 3D models from text.</p>
            <div style={{ margin: "0.75rem 0", display: "flex", gap: "1.5rem" }}>
                {(["meshy", "tripo"] as Provider[]).map((p) => (
                    <label key={p} style={{ cursor: "pointer" }}>
                        <input
                            type="radio"
                            value={p}
                            checked={provider === p}
                            onChange={() => setProvider(p)}
                            style={{ marginRight: "0.35rem" }}
                        />
                        {PROVIDER_LABELS[p]}
                    </label>
                ))}
            </div>
            <p style={{ fontSize: "0.82rem", color: "#888", marginTop: 0 }}>
                Your key is stored in Windows Credential Manager and never leaves your machine.
            </p>
            {keyAlreadySet === true && !saved && (
                <p style={{ color: "green" }}>A {label} API key is already saved.</p>
            )}
            {keyAlreadySet === false && (
                <p style={{ color: "orange" }}>No {label} key found. Enter it below.</p>
            )}
            <div style={{ marginTop: "0.5rem" }}>
                <input
                    type="password"
                    placeholder={KEY_PLACEHOLDER[provider]}
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
                    <button className="btn-primary" onClick={() => onComplete({ generation_provider: provider })}>
                        Continue
                    </button>
                )}
            </div>
        </div>
    );
}
