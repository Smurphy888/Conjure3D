import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { invokeSidecar } from "../lib/ipc";
import { describeBackend } from "../lib/backendStatus";

type Provider = "local" | "openrouter" | "openai";

interface ProviderInfo {
    provider: Provider;
    model: string | null;
    has_openrouter_key: boolean;
    has_openai_key: boolean;
}

interface SetProviderResult {
    ok: boolean;
    message?: string;
    degraded?: boolean;
    backend?: string;
}

const META: Record<Provider, { label: string; blurb: string; keyCmd?: string; keyHint?: string }> = {
    local: {
        label: "Local (on this PC)",
        blurb: "Runs the bundled model on your CPU. Free and offline, but won't load on older CPUs (then it falls back to basic keyword mode).",
    },
    openrouter: {
        label: "OpenRouter",
        blurb: "One key, many models. Default is the non-Anthropic Qwen coder.",
        keyCmd: "system.set_openrouter_key",
        keyHint: "OpenRouter key — starts with sk-or-v1-  (get one at openrouter.ai/keys)",
    },
    openai: {
        label: "OpenAI",
        blurb: "Direct OpenAI. Default model gpt-4o-mini.",
        keyCmd: "system.set_openai_key",
        keyHint: "OpenAI key — starts with sk-  (platform.openai.com/api-keys)",
    },
};

export function Settings() {
    const navigate = useNavigate();
    const [provider, setProvider] = useState<Provider>("local");
    const [model, setModel] = useState("");
    const [key, setKey] = useState("");
    const [hasKey, setHasKey] = useState<{ openrouter: boolean; openai: boolean }>({
        openrouter: false,
        openai: false,
    });
    const [modeLabel, setModeLabel] = useState("…");
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [success, setSuccess] = useState<string | null>(null);

    async function loadStatus() {
        const info = await invokeSidecar<ProviderInfo>("llm.get_provider");
        setProvider(info.provider);
        setHasKey({ openrouter: info.has_openrouter_key, openai: info.has_openai_key });
        const be = await invokeSidecar<{ backend: string; install_status?: string; degraded?: boolean }>(
            "llm.backend_info"
        );
        setModeLabel(describeBackend(be.backend, be.install_status, be.degraded).label);
    }

    useEffect(() => {
        loadStatus().catch((e) => setError(String(e)));
    }, []);

    const keyAlreadySaved =
        provider === "openrouter" ? hasKey.openrouter : provider === "openai" ? hasKey.openai : false;

    async function apply() {
        setSaving(true);
        setError(null);
        setSuccess(null);
        try {
            const meta = META[provider];
            if (meta.keyCmd && key.trim()) {
                await invokeSidecar(meta.keyCmd, { key: key.trim() });
            }
            const res = await invokeSidecar<SetProviderResult>("llm.set_provider", {
                provider,
                ...(model.trim() ? { model: model.trim() } : {}),
            });
            if (!res.ok) {
                setError(res.message || "Couldn't switch provider.");
            } else {
                setKey("");
                setSuccess(
                    provider === "local"
                        ? "Switched to local mode."
                        : `Connected — now using ${META[provider].label}.`
                );
            }
            await loadStatus();
        } catch (e) {
            setError(String(e));
        } finally {
            setSaving(false);
        }
    }

    return (
        <div className="container">
            <h2>Settings</h2>
            <div style={{ textAlign: "left", maxWidth: 560 }}>
                <p style={{ fontSize: "0.9rem", color: "var(--text-muted)" }}>
                    Current AI mode: <strong style={{ color: "var(--text)" }}>{modeLabel}</strong>
                </p>

                <h3 style={{ fontSize: "1.05rem", marginBottom: "0.4rem" }}>AI Editor model</h3>
                <p style={{ fontSize: "0.82rem", color: "var(--text-muted)", marginTop: 0 }}>
                    Which model turns your words into edits. (Separate from the 3D model
                    generator — that's Meshy/Tripo.)
                </p>

                <div style={{ display: "grid", gap: "0.5rem", margin: "0.75rem 0" }}>
                    {(["local", "openrouter", "openai"] as Provider[]).map((p) => (
                        <label
                            key={p}
                            style={{
                                display: "flex",
                                gap: "0.6rem",
                                alignItems: "flex-start",
                                padding: "0.6rem 0.7rem",
                                border: `1px solid ${provider === p ? "var(--accent)" : "var(--border)"}`,
                                borderRadius: "var(--radius-sm)",
                                background: provider === p ? "var(--accent-soft)" : "var(--surface)",
                                cursor: "pointer",
                            }}
                        >
                            <input
                                type="radio"
                                name="llm-provider"
                                checked={provider === p}
                                onChange={() => {
                                    setProvider(p);
                                    setError(null);
                                    setSuccess(null);
                                    setKey("");
                                }}
                                style={{ marginTop: "0.2rem" }}
                            />
                            <span>
                                <span style={{ fontWeight: 600 }}>{META[p].label}</span>
                                {(p === "openrouter" && hasKey.openrouter) ||
                                (p === "openai" && hasKey.openai) ? (
                                    <span style={{ color: "var(--success)", fontSize: "0.78rem" }}> · key saved</span>
                                ) : null}
                                <span style={{ display: "block", fontSize: "0.8rem", color: "var(--text-muted)" }}>
                                    {META[p].blurb}
                                </span>
                            </span>
                        </label>
                    ))}
                </div>

                {provider !== "local" && (
                    <div style={{ display: "grid", gap: "0.4rem", marginBottom: "0.6rem" }}>
                        <input
                            type="password"
                            placeholder={
                                keyAlreadySaved
                                    ? "Replace saved key (leave blank to keep it)"
                                    : META[provider].keyHint
                            }
                            value={key}
                            onChange={(e) => setKey(e.target.value)}
                            disabled={saving}
                        />
                        <input
                            type="text"
                            placeholder="Model (optional) — leave blank for the default"
                            value={model}
                            onChange={(e) => setModel(e.target.value)}
                            disabled={saving}
                        />
                        <span style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
                            Keys are stored in Windows Credential Manager and never logged. The
                            key is checked live when you apply — a bad key is rejected here, not
                            silently.
                        </span>
                    </div>
                )}

                <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.4rem" }}>
                    <button className="btn-primary" onClick={apply} disabled={saving}>
                        {saving ? "Applying…" : "Save & apply"}
                    </button>
                    <button onClick={() => navigate("/")} disabled={saving}>
                        Back
                    </button>
                </div>

                {error && (
                    <p style={{ color: "var(--danger)", fontSize: "0.85rem", whiteSpace: "pre-wrap" }}>{error}</p>
                )}
                {success && <p style={{ color: "var(--success)", fontSize: "0.85rem" }}>{success}</p>}
            </div>
        </div>
    );
}
