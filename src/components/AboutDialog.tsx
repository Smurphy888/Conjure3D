/**
 * Phase I Issue #28 — About dialog (thin glue over src/lib/about.ts).
 * Phase I Issue #29 — hosts the "Copy diagnostic" button (last 200 log
 * lines + project state → clipboard) since it already shows version/build.
 *
 * Rendered as a small link on the Home screen (not a second fixed corner
 * element — the ConnectionBadge already owns a screen corner). Reuses the
 * .conn-modal* overlay styles so there is one modal look across the app.
 */
import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { getAbout } from "../lib/about";
import { buildDiagnostic } from "../lib/diagnostic";
import { useProjectState } from "../lib/projectState";

export function AboutDialog() {
    const [open, setOpen] = useState(false);
    const [status, setStatus] = useState<string | null>(null);
    const about = getAbout();
    const project = useProjectState();

    async function copyDiagnostic() {
        setStatus(null);
        try {
            const { path, contents } = await invoke<{
                path: string;
                contents: string;
            }>("read_diagnostic_log");
            const text = buildDiagnostic({
                appName: about.name,
                version: about.version,
                buildDate: about.buildDate,
                logPath: path,
                logText: contents,
                project,
            });
            await navigator.clipboard.writeText(text);
            setStatus("Diagnostic copied to clipboard.");
        } catch (e) {
            setStatus(`Could not copy diagnostic: ${String(e)}`);
        }
    }

    return (
        <>
            <button
                type="button"
                className="link-button"
                onClick={() => setOpen(true)}
            >
                About
            </button>

            {open && (
                <div className="conn-modal-overlay" onClick={() => setOpen(false)}>
                    <div
                        className="conn-modal"
                        onClick={(e) => e.stopPropagation()}
                        role="dialog"
                        aria-modal="true"
                    >
                        <h3>{about.name}</h3>
                        <p>
                            Version <strong>{about.version}</strong>
                        </p>
                        <p style={{ fontSize: "0.85rem", color: "#aaa" }}>
                            Build date: {about.buildDate}
                        </p>
                        {status && (
                            <p style={{ fontSize: "0.8rem", color: "#a855f7" }}>
                                {status}
                            </p>
                        )}
                        <div
                            style={{
                                display: "flex",
                                gap: "0.5rem",
                                marginTop: "0.75rem",
                                justifyContent: "center",
                            }}
                        >
                            <button onClick={copyDiagnostic}>Copy diagnostic</button>
                            <button onClick={() => setOpen(false)}>Close</button>
                        </div>
                    </div>
                </div>
            )}
        </>
    );
}
