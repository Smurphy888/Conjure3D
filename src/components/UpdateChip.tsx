import { useEffect, useState } from "react";
import { check, type Update } from "@tauri-apps/plugin-updater";
import { relaunch } from "@tauri-apps/plugin-process";

/**
 * Auto-update UX (LAUNCH_AUDIT 1.3). Checks the release feed once, shortly
 * after startup, and shows a small chip when a newer version exists. The
 * check is best-effort: offline, endpoint-not-yet-live (no GitHub repo
 * published), or signature errors all fail silently — the app must never
 * nag or break because the update path is unavailable.
 *
 * Install flow: downloadAndInstall streams the NSIS updater artifact
 * (signature-verified against the pubkey pinned in tauri.conf.json),
 * then relaunch() restarts into the new version. "Later" dismisses for
 * this session only — the next launch re-offers it.
 */
export function UpdateChip() {
    const [update, setUpdate] = useState<Update | null>(null);
    const [phase, setPhase] = useState<"idle" | "installing" | "error">("idle");
    const [dismissed, setDismissed] = useState(false);

    useEffect(() => {
        // Delay so the check never competes with first-paint / sidecar spawn.
        const t = setTimeout(() => {
            check()
                .then((u) => {
                    if (u) setUpdate(u);
                })
                .catch(() => {
                    // Silent by design — see component docstring.
                });
        }, 5000);
        return () => clearTimeout(t);
    }, []);

    if (!update || dismissed) return null;

    async function install() {
        if (!update) return;
        setPhase("installing");
        try {
            await update.downloadAndInstall();
            await relaunch();
        } catch {
            setPhase("error");
        }
    }

    return (
        <div
            style={{
                position: "fixed",
                bottom: "1rem",
                left: "1rem",
                zIndex: 1000,
                background: "var(--surface)",
                border: "1px solid var(--border)",
                borderRadius: 10,
                padding: "0.6rem 0.9rem",
                display: "flex",
                alignItems: "center",
                gap: "0.6rem",
                fontSize: "0.85rem",
                boxShadow: "0 4px 24px rgba(0,0,0,0.4)",
            }}
        >
            {phase === "error" ? (
                <>
                    <span>Update failed — try again later.</span>
                    <button onClick={() => setDismissed(true)}>Dismiss</button>
                </>
            ) : (
                <>
                    <span>
                        Conjure3D {update.version} is available
                    </span>
                    <button onClick={install} disabled={phase === "installing"}>
                        {phase === "installing" ? "Installing…" : "Update & restart"}
                    </button>
                    <button onClick={() => setDismissed(true)} disabled={phase === "installing"}>
                        Later
                    </button>
                </>
            )}
        </div>
    );
}
