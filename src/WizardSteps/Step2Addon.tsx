import { useEffect, useState } from "react";
import { invokeSidecar } from "../lib/ipc";

interface DetectResult {
    found: boolean;
    path: string | null;
    version: string | null;
}

interface InstallResult {
    ok: boolean;
    path?: string;
    error?: string;
}

interface Props {
    onComplete: () => void;
}

type Phase = "detecting" | "installing" | "done" | "error";

export function Step2Addon({ onComplete }: Props) {
    const [phase, setPhase] = useState<Phase>("detecting");
    const [message, setMessage] = useState<string>("Detecting your Blender install...");
    const [addonPath, setAddonPath] = useState<string | null>(null);

    async function runInstall() {
        setPhase("detecting");
        setMessage("Detecting your Blender install...");
        try {
            const detect = await invokeSidecar<DetectResult>("wizard.detect_blender");
            if (!detect.found || !detect.version) {
                setPhase("error");
                setMessage(
                    "Blender wasn't detected. Go back to Step 1 and install Blender 4.2 LTS or later."
                );
                return;
            }
            setPhase("installing");
            setMessage(`Installing patched BlenderMCP addon for Blender ${detect.version}...`);
            const install = await invokeSidecar<InstallResult>("wizard.install_addon", {
                blender_version: detect.version,
            });
            if (install.ok) {
                setAddonPath(install.path ?? null);
                setPhase("done");
                setMessage(
                    "BlenderMCP addon installed. Enable it inside Blender at Edit → Preferences → Add-ons (search for “Blender MCP”) and tick the checkbox."
                );
            } else {
                setPhase("error");
                setMessage(`Install failed: ${install.error ?? "unknown error"}`);
            }
        } catch (e) {
            setPhase("error");
            setMessage(`Could not contact the sidecar: ${String(e)}`);
        }
    }

    useEffect(() => {
        runInstall();
        // run-once: deliberately empty deps. retry handled by the Retry button.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const color =
        phase === "done" ? "green" : phase === "error" ? "red" : "var(--text)";

    return (
        <div>
            <h2>Step 2: BlenderMCP Addon</h2>
            <p>
                Conjure3D ships a patched copy of the BlenderMCP add-on (the upstream
                build has a connection-stability bug that breaks edit chains on
                Windows). This step extracts it into your Blender add-ons folder.
            </p>
            <p style={{ color }}>{message}</p>
            {phase === "done" && addonPath && (
                <p style={{ color: "var(--text-dim, #888)", fontSize: "0.9rem" }}>
                    Extracted to: <code>{addonPath}</code>
                </p>
            )}
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem" }}>
                {phase === "error" && (
                    <button onClick={runInstall}>Retry</button>
                )}
                {phase === "done" && (
                    <button onClick={() => onComplete()}>Continue</button>
                )}
            </div>
        </div>
    );
}
