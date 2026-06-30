/**
 * Phase I Issue #27 — Blender socket status badge + Reconnect dialog.
 *
 * Rendered once at App level so it floats over every screen (fixed position,
 * outside the centered .container flow). Click → modal with a Reconnect
 * button (forces one immediate probe) and the manual recovery steps.
 */
import { useState } from "react";
import { useConnection } from "../lib/connectionContext";

const LABEL: Record<string, string> = {
    checking: "Blender: checking…",
    connected: "Blender: connected",
    disconnected: "Blender: disconnected",
};

export function ConnectionBadge() {
    const { state, lastError, reconnect } = useConnection();
    const [open, setOpen] = useState(false);
    const [reconnecting, setReconnecting] = useState(false);

    async function handleReconnect() {
        setReconnecting(true);
        try {
            await reconnect();
        } finally {
            setReconnecting(false);
        }
    }

    return (
        <>
            <button
                type="button"
                className={`conn-badge conn-${state}`}
                onClick={() => setOpen(true)}
                title="Blender connection status — click for details"
            >
                <span className="conn-dot" />
                {LABEL[state]}
            </button>

            {open && (
                <div className="conn-modal-overlay" onClick={() => setOpen(false)}>
                    <div
                        className="conn-modal"
                        onClick={(e) => e.stopPropagation()}
                        role="dialog"
                        aria-modal="true"
                    >
                        <h3>Blender connection</h3>
                        <p>
                            Status:{" "}
                            <strong className={`conn-${state}`}>{LABEL[state]}</strong>
                        </p>
                        {state !== "connected" && (
                            <>
                                {lastError && (
                                    <p style={{ color: "#ff6b6b", fontSize: "0.85rem" }}>
                                        {lastError}
                                    </p>
                                )}
                                <ol style={{ textAlign: "left", lineHeight: 1.5 }}>
                                    <li>Open Blender.</li>
                                    <li>Press <strong>N</strong> for the sidebar, open the <strong>BlenderMCP</strong> tab.</li>
                                    <li>Click <strong>Connect to Claude</strong>.</li>
                                    <li>Press <strong>Reconnect</strong> below.</li>
                                </ol>
                            </>
                        )}
                        <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem", justifyContent: "center" }}>
                            <button onClick={handleReconnect} disabled={reconnecting}>
                                {reconnecting ? "Reconnecting…" : "Reconnect"}
                            </button>
                            <button onClick={() => setOpen(false)}>Close</button>
                        </div>
                    </div>
                </div>
            )}
        </>
    );
}
