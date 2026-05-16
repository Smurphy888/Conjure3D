/**
 * Phase I Issue #28 — About dialog (thin glue over src/lib/about.ts).
 *
 * Rendered as a small link on the Home screen (not a second fixed corner
 * element — the ConnectionBadge already owns a screen corner). Reuses the
 * .conn-modal* overlay styles so there is one modal look across the app.
 */
import { useState } from "react";
import { getAbout } from "../lib/about";

export function AboutDialog() {
    const [open, setOpen] = useState(false);
    const about = getAbout();

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
                        <div style={{ marginTop: "0.75rem", textAlign: "center" }}>
                            <button onClick={() => setOpen(false)}>Close</button>
                        </div>
                    </div>
                </div>
            )}
        </>
    );
}
