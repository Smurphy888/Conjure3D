/**
 * Phase I Issue #27 — Blender socket connection status (pure, testable core).
 *
 * The React layer (blenderConnectionContext.tsx, ConnectionBadge.tsx) is thin
 * glue over these functions; everything that has logic worth testing lives
 * here and is unit-tested with no DOM and no testing-library (matching the
 * repo's pure-vitest convention).
 *
 * Cadence: one fresh `wizard.test_socket` TCP probe every POLL_INTERVAL_MS.
 * Over a long session that is ~720 connections/hour — intentional and fine
 * for BlenderMCP. Do NOT drop the interval to 1s in a "tighten polling" PR;
 * it looks fine in dev and hammers the serialized addon in real use.
 */

export const POLL_INTERVAL_MS = 5000;

export type ConnState = "checking" | "connected" | "disconnected";

export interface ProbeResult {
    connected: boolean;
    error?: string;
}

/** Run one probe via the injected sidecar caller. Never throws: a failed
 *  sidecar call is normalised to a disconnected result so the poller's
 *  state machine only ever deals with ProbeResult. */
export async function probeConnection(
    invoke: <T>(method: string) => Promise<T>,
): Promise<ProbeResult> {
    try {
        const r = await invoke<ProbeResult>("wizard.test_socket");
        return { connected: !!r?.connected, error: r?.error };
    } catch (e) {
        return { connected: false, error: `Sidecar call failed: ${String(e)}` };
    }
}

/** `null` = no probe has returned yet (startup). */
export function classifyConnection(result: ProbeResult | null): ConnState {
    if (result === null) return "checking";
    return result.connected ? "connected" : "disconnected";
}

/**
 * Whether the edit chain may run, and the message to show when it may not.
 *
 * STRICT by design: Apply is allowed ONLY when the connection is proven
 * green. During the brief "checking" window on mount (resolves in <2s when
 * the first probe returns) Apply stays disabled. This matches the ISSUES.md
 * #27 acceptance wording ("blocked while red") literally — do not relax this
 * to an optimistic "allow unless proven red" without a deliberate decision.
 */
export function editChainGate(
    state: ConnState,
): { allowed: boolean; message: string | null } {
    if (state === "connected") return { allowed: true, message: null };
    if (state === "checking") {
        return { allowed: false, message: "Checking Blender connection…" };
    }
    return {
        allowed: false,
        message:
            "Blender is not connected. Open Blender, click " +
            "“Connect to Claude” in the BlenderMCP panel, then retry.",
    };
}

/**
 * Drive `probe` immediately, then every `intervalMs`. Returns a cleanup that
 * stops the loop. Designed against the three production bugs:
 *  - overlap: a slow probe (2s timeout) will not start a second probe;
 *  - unmount race: results arriving after stop() are dropped;
 *  - startup latency: the first probe fires immediately, not after one
 *    interval.
 */
export function startPolling(opts: {
    probe: () => Promise<ProbeResult>;
    onResult: (r: ProbeResult) => void;
    intervalMs?: number;
}): () => void {
    const interval = opts.intervalMs ?? POLL_INTERVAL_MS;
    let cancelled = false;
    let inFlight = false;

    async function tick() {
        if (cancelled || inFlight) return;
        inFlight = true;
        try {
            const r = await opts.probe();
            if (!cancelled) opts.onResult(r);
        } finally {
            inFlight = false;
        }
    }

    void tick();
    const id = setInterval(tick, interval);

    return () => {
        cancelled = true;
        clearInterval(id);
    };
}
