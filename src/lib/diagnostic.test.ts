import { describe, it, expect } from "vitest";
import { tailLines, buildDiagnostic } from "./diagnostic";

describe("tailLines", () => {
    it("empty text → no lines", () => {
        expect(tailLines("", 200)).toEqual([]);
    });

    it("fewer lines than n → all of them", () => {
        expect(tailLines("a\nb\nc", 200)).toEqual(["a", "b", "c"]);
    });

    it("more lines than n → only the last n", () => {
        const text = Array.from({ length: 500 }, (_, i) => `line${i}`).join("\n");
        const out = tailLines(text, 200);
        expect(out).toHaveLength(200);
        expect(out[0]).toBe("line300");
        expect(out[199]).toBe("line499");
    });

    it("ignores a single trailing newline", () => {
        expect(tailLines("a\nb\n", 10)).toEqual(["a", "b"]);
    });

    it("handles CRLF", () => {
        expect(tailLines("a\r\nb\r\nc\r\n", 2)).toEqual(["b", "c"]);
    });

    it("n <= 0 → no lines", () => {
        expect(tailLines("a\nb", 0)).toEqual([]);
    });
});

describe("buildDiagnostic", () => {
    const base = {
        appName: "Conjure3D",
        version: "0.0.1",
        buildDate: "2026-05-16 23:07 UTC",
        logPath: "C:\\Users\\x\\AppData\\Local\\Conjure3D\\logs\\sidecar-1.log",
        logText: "boot\n[sidecar] internal error in edit.apply_chain: boom\nTraceback (most recent call last):\n  File ...\nRuntimeError: boom\n",
        project: { name: "vase", prompt: "a vase", edits: [] },
    };

    it("includes version, build date, log path and project state", () => {
        const out = buildDiagnostic(base);
        expect(out).toContain("Conjure3D diagnostic");
        expect(out).toContain("Version: 0.0.1");
        expect(out).toContain("Build date: 2026-05-16 23:07 UTC");
        expect(out).toContain("sidecar-1.log");
        expect(out).toContain('"name": "vase"');
        expect(out).toContain("Traceback (most recent call last):");
        expect(out).toContain("RuntimeError: boom");
    });

    it("respects maxLogLines and reports the real count", () => {
        const text = Array.from({ length: 50 }, (_, i) => `L${i}`).join("\n");
        const out = buildDiagnostic({ ...base, logText: text, maxLogLines: 10 });
        expect(out).toContain("--- Last 10 log line(s) ---");
        expect(out).toContain("L49");
        expect(out).not.toContain("\nL39\n"); // L40..L49 only
    });

    it("never throws on a circular project state", () => {
        const circular: Record<string, unknown> = {};
        circular.self = circular;
        const out = buildDiagnostic({ ...base, project: circular });
        expect(out).toContain("<unserialisable project state>");
    });
});
