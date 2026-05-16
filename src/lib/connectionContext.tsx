/**
 * Phase I Issue #27 — React glue over the pure connection core.
 *
 * One poller for the whole app: mounted once at App level (inside
 * ProjectProvider, around the routes) so the badge and the Editor's Apply
 * gate read the same live state. Do NOT instantiate a second provider
 * per-screen — that would double the `wizard.test_socket` probe rate against
 * the serialized BlenderMCP addon.
 */
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { invokeSidecar } from "./ipc";
import {
    classifyConnection,
    probeConnection,
    startPolling,
    type ConnState,
    type ProbeResult,
} from "./blenderConnection";

export interface ConnectionValue {
    state: ConnState;
    /** Last probe's error text when disconnected, else null. */
    lastError: string | null;
    /** Force one immediate probe (used by the Reconnect dialog button). */
    reconnect: () => Promise<void>;
}

const ConnectionCtx = createContext<ConnectionValue>({
    state: "checking",
    lastError: null,
    reconnect: async () => {},
});

export function ConnectionProvider({ children }: { children: ReactNode }) {
    const [result, setResult] = useState<ProbeResult | null>(null);

    useEffect(() => {
        // startPolling probes immediately then every POLL_INTERVAL_MS, never
        // overlaps a slow probe, and drops results that land after unmount.
        return startPolling({
            probe: () => probeConnection(invokeSidecar),
            onResult: setResult,
        });
    }, []);

    const reconnect = useCallback(async () => {
        const r = await probeConnection(invokeSidecar);
        setResult(r);
    }, []);

    const state = classifyConnection(result);
    const lastError = result && !result.connected ? result.error ?? null : null;

    return (
        <ConnectionCtx.Provider value={{ state, lastError, reconnect }}>
            {children}
        </ConnectionCtx.Provider>
    );
}

export function useConnection(): ConnectionValue {
    return useContext(ConnectionCtx);
}
