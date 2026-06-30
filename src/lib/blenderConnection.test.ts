import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
    probeConnection,
    classifyConnection,
    editChainGate,
    startPolling,
    POLL_INTERVAL_MS,
} from "./blenderConnection";

describe("probeConnection", () => {
    it("normalises a successful socket test", async () => {
        const invoke = vi.fn().mockResolvedValue({ connected: true });
        expect(await probeConnection(invoke)).toEqual({ connected: true, error: undefined });
        expect(invoke).toHaveBeenCalledWith("wizard.test_socket");
    });

    it("passes through the addon error message", async () => {
        const invoke = vi.fn().mockResolvedValue({ connected: false, error: "refused" });
        expect(await probeConnection(invoke)).toEqual({ connected: false, error: "refused" });
    });

    it("never throws — a failed sidecar call is disconnected", async () => {
        const invoke = vi.fn().mockRejectedValue(new Error("pipe broke"));
        const r = await probeConnection(invoke);
        expect(r.connected).toBe(false);
        expect(r.error).toContain("pipe broke");
    });
});

describe("classifyConnection", () => {
    it("null → checking (no probe returned yet)", () => {
        expect(classifyConnection(null)).toBe("checking");
    });
    it("connected true → connected", () => {
        expect(classifyConnection({ connected: true })).toBe("connected");
    });
    it("connected false → disconnected", () => {
        expect(classifyConnection({ connected: false, error: "x" })).toBe("disconnected");
    });
});

describe("editChainGate (strict)", () => {
    it("allows only when connected", () => {
        expect(editChainGate("connected")).toEqual({ allowed: true, message: null });
    });
    it("blocks during checking with a message", () => {
        const g = editChainGate("checking");
        expect(g.allowed).toBe(false);
        expect(g.message).toBeTruthy();
    });
    it("blocks when disconnected with reconnect guidance", () => {
        const g = editChainGate("disconnected");
        expect(g.allowed).toBe(false);
        expect(g.message).toContain("Connect to Claude");
    });
});

describe("startPolling lifecycle", () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it("probes immediately, then every interval", async () => {
        const probe = vi.fn().mockResolvedValue({ connected: true });
        const onResult = vi.fn();
        const stop = startPolling({ probe, onResult });
        // immediate
        await vi.advanceTimersByTimeAsync(0);
        expect(probe).toHaveBeenCalledTimes(1);
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
        expect(probe).toHaveBeenCalledTimes(2);
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
        expect(probe).toHaveBeenCalledTimes(3);
        expect(onResult).toHaveBeenCalledTimes(3);
        stop();
    });

    it("does not overlap a slow probe", async () => {
        let resolve: (v: { connected: boolean }) => void = () => {};
        const probe = vi.fn().mockImplementation(
            () => new Promise((r) => { resolve = r; }),
        );
        const onResult = vi.fn();
        const stop = startPolling({ probe, onResult });
        await vi.advanceTimersByTimeAsync(0);
        expect(probe).toHaveBeenCalledTimes(1);
        // interval fires while first probe is still pending → skipped
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
        expect(probe).toHaveBeenCalledTimes(1);
        resolve({ connected: true });
        await vi.advanceTimersByTimeAsync(0);
        // next interval after it resolved → runs again
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
        expect(probe).toHaveBeenCalledTimes(2);
        stop();
    });

    it("drops results that arrive after stop() (unmount race)", async () => {
        let resolve: (v: { connected: boolean }) => void = () => {};
        const probe = vi.fn().mockImplementation(
            () => new Promise((r) => { resolve = r; }),
        );
        const onResult = vi.fn();
        const stop = startPolling({ probe, onResult });
        await vi.advanceTimersByTimeAsync(0);
        stop();
        resolve({ connected: true });
        await vi.advanceTimersByTimeAsync(0);
        expect(onResult).not.toHaveBeenCalled();
    });

    it("stop() halts the interval", async () => {
        const probe = vi.fn().mockResolvedValue({ connected: false });
        const stop = startPolling({ probe, onResult: vi.fn() });
        await vi.advanceTimersByTimeAsync(0);
        stop();
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3);
        expect(probe).toHaveBeenCalledTimes(1);
    });
});
