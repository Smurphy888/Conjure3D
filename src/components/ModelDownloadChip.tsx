/**
 * Phase J.5 — model download progress chip.
 *
 * Floats in the lower-right above the ConnectionBadge so the user always
 * has a glance-able read on "is the AI model downloading / done / failed?"
 * without having to dig into a settings screen.
 *
 * Visibility rules (kept deliberately quiet so it doesn't intrude during
 * non-AI flows):
 *
 *   - hidden when: phase=idle AND model_present (the steady-state "all
 *     good, model is on disk" case — no need to nag)
 *   - hidden when: phase=idle AND NOT model_present AND no other UI
 *     surface (Settings, AI Editor) has triggered a download yet
 *   - visible when: phase ∈ {checking, downloading, verifying} — show
 *     progress
 *   - visible when: phase ∈ {error, cancelled} — surface what went
 *     wrong with a Retry path
 *   - visible briefly when: phase=done (3-second toast) to confirm
 *     the prefetch finished
 *
 * Click → modal with full status, cancel + retry buttons, and the
 * destination path so power users can verify on disk.
 *
 * Polling: every 1000 ms while phase is non-terminal. We could lean on
 * a sidecar event channel later, but polling is the existing pattern
 * (ConnectionBadge does the same).
 */
import { useEffect, useState } from "react";
import { invokeSidecar } from "../lib/ipc";

interface ModelStatus {
    phase: "idle" | "checking" | "downloading" | "verifying" | "done" | "cancelled" | "error";
    bytes_done: number;
    bytes_total: number | null;
    sha256: string | null;
    error: string | null;
    started_at: number | null;
    finished_at: number | null;
    dest_path: string;
    model_present: boolean;
    url: string;
}

const ACTIVE_PHASES = new Set(["checking", "downloading", "verifying"]);

function formatBytes(n: number): string {
    if (n < 1024) return `${n} B`;
    const units = ["KB", "MB", "GB", "TB"];
    let v = n / 1024;
    for (const u of units) {
        if (v < 1024) return `${v.toFixed(1)} ${u}`;
        v /= 1024;
    }
    return `${v.toFixed(1)} PB`;
}

function progressPercent(s: ModelStatus): number | null {
    if (!s.bytes_total || s.bytes_total <= 0) return null;
    return Math.min(100, Math.round((s.bytes_done / s.bytes_total) * 100));
}

function shortLabel(s: ModelStatus): string {
    switch (s.phase) {
        case "checking":
            return "AI model: checking…";
        case "downloading": {
            const pct = progressPercent(s);
            return pct === null
                ? `AI model: ${formatBytes(s.bytes_done)} downloaded`
                : `AI model: ${pct}%`;
        }
        case "verifying":
            return "AI model: verifying…";
        case "done":
            return "AI model: ready ✓";
        case "cancelled":
            return "AI model: cancelled";
        case "error":
            return "AI model: failed";
        default:
            return "AI model";
    }
}

export function ModelDownloadChip() {
    const [status, setStatus] = useState<ModelStatus | null>(null);
    const [open, setOpen] = useState(false);
    const [acting, setActing] = useState(false);
    // Once a "done" transition happens we show a brief confirmation
    // toast, then hide. This timestamp tracks when we first saw "done"
    // so the chip auto-dismisses 3 s later.
    const [doneAt, setDoneAt] = useState<number | null>(null);

    // Poll. While the phase is active, every 1 s; while terminal, less
    // often (every 5 s) so the chip eventually picks up an out-of-band
    // download that some other UI triggered.
    useEffect(() => {
        let cancelled = false;
        let timer: ReturnType<typeof setTimeout> | null = null;

        async function poll() {
            try {
                const next = await invokeSidecar<ModelStatus>("llm.model_status");
                if (cancelled) return;
                setStatus((prev) => {
                    if (next.phase === "done" && prev?.phase !== "done") {
                        setDoneAt(Date.now());
                    }
                    return next;
                });
                const delay = ACTIVE_PHASES.has(next.phase) ? 1000 : 5000;
                timer = setTimeout(poll, delay);
            } catch {
                if (cancelled) return;
                timer = setTimeout(poll, 5000);
            }
        }
        void poll();
        return () => {
            cancelled = true;
            if (timer) clearTimeout(timer);
        };
    }, []);

    async function handleRetry() {
        setActing(true);
        try {
            await invokeSidecar("llm.download_start");
        } finally {
            setActing(false);
        }
    }

    async function handleCancel() {
        setActing(true);
        try {
            await invokeSidecar("llm.download_cancel");
        } finally {
            setActing(false);
        }
    }

    if (!status) return null;

    // Visibility decisions
    const isActive = ACTIVE_PHASES.has(status.phase);
    const isError = status.phase === "error" || status.phase === "cancelled";
    const showDoneToast =
        status.phase === "done" && doneAt !== null && Date.now() - doneAt < 3000;
    const visible = isActive || isError || showDoneToast;
    if (!visible) return null;

    const label = shortLabel(status);
    const pct = progressPercent(status);
    const colour =
        status.phase === "error"
            ? "#ff6b6b"
            : status.phase === "done"
                ? "#2ecc71"
                : status.phase === "cancelled"
                    ? "#f5a623"
                    : "#a855f7";

    return (
        <>
            <button
                type="button"
                onClick={() => setOpen(true)}
                className="conn-badge"
                style={{
                    // Sit above the ConnectionBadge (which uses bottom: 12px)
                    bottom: 50,
                    color: colour,
                    borderColor: "#333",
                }}
                title="AI model status — click for details"
            >
                <span
                    style={{
                        display: "inline-block",
                        width: 9,
                        height: 9,
                        borderRadius: "50%",
                        background: colour,
                    }}
                />
                {label}
            </button>
            {open && (
                <div className="conn-modal-overlay" onClick={() => setOpen(false)}>
                    <div
                        className="conn-modal"
                        onClick={(e) => e.stopPropagation()}
                        role="dialog"
                        aria-modal="true"
                    >
                        <h3>AI model</h3>
                        <p style={{ fontSize: "0.9rem", textAlign: "left", marginBottom: "0.5rem" }}>
                            Conjure3D uses a 4.4 GB local AI model
                            (Qwen2.5-Coder-7B-Instruct Q4_K_M) to turn your
                            natural-language edit requests into Blender
                            operations. The download runs once.
                        </p>
                        <p style={{ fontSize: "0.85rem", textAlign: "left" }}>
                            <strong>Phase:</strong> {status.phase}
                            <br />
                            <strong>Progress:</strong>{" "}
                            {pct !== null
                                ? `${pct}% (${formatBytes(status.bytes_done)} / ${status.bytes_total ? formatBytes(status.bytes_total) : "?"})`
                                : formatBytes(status.bytes_done)}
                            <br />
                            <strong>File:</strong>{" "}
                            <code style={{ wordBreak: "break-all" }}>{status.dest_path}</code>
                            {status.sha256 && (
                                <>
                                    <br />
                                    <strong>SHA256:</strong>{" "}
                                    <code style={{ fontSize: "0.75rem", wordBreak: "break-all" }}>
                                        {status.sha256}
                                    </code>
                                </>
                            )}
                            {status.error && (
                                <>
                                    <br />
                                    <strong style={{ color: "#ff6b6b" }}>Error:</strong>{" "}
                                    <span style={{ color: "#ff6b6b" }}>{status.error}</span>
                                </>
                            )}
                        </p>
                        <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem", justifyContent: "center", flexWrap: "wrap" }}>
                            {isActive && (
                                <button onClick={handleCancel} disabled={acting}>
                                    {acting ? "Cancelling…" : "Cancel download"}
                                </button>
                            )}
                            {(isError || status.phase === "idle") && (
                                <button onClick={handleRetry} disabled={acting}>
                                    {acting ? "Starting…" : "Start / Retry download"}
                                </button>
                            )}
                            <button onClick={() => setOpen(false)}>Close</button>
                        </div>
                    </div>
                </div>
            )}
        </>
    );
}
