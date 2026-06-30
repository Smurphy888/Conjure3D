import { describe, it, expect } from "vitest";
import { formatBuildDate, getAbout, appVersion, APP_NAME } from "./about";

describe("formatBuildDate", () => {
    it("formats a valid ISO timestamp as stable UTC", () => {
        expect(formatBuildDate("2026-05-16T23:07:09.000Z")).toBe(
            "2026-05-16 23:07 UTC",
        );
    });

    it("zero-pads month/day/hour/minute", () => {
        expect(formatBuildDate("2026-01-02T03:04:00.000Z")).toBe(
            "2026-01-02 03:04 UTC",
        );
    });

    it("is timezone-independent (formats in UTC, not local)", () => {
        // A pre-midnight-UTC instant must not roll the date backward/forward.
        expect(formatBuildDate("2026-12-31T23:59:00.000Z")).toBe(
            "2026-12-31 23:59 UTC",
        );
    });

    it("empty string → unknown (never 'Invalid Date')", () => {
        expect(formatBuildDate("")).toBe("unknown");
    });

    it("garbage input → unknown", () => {
        expect(formatBuildDate("not-a-date")).toBe("unknown");
    });
});

describe("getAbout", () => {
    it("returns name, version and a formatted build date", () => {
        const a = getAbout();
        expect(a.name).toBe(APP_NAME);
        expect(a.name).toBe("Conjure3D");
        expect(typeof a.version).toBe("string");
        expect(a.version.length).toBeGreaterThan(0);
        expect(typeof a.buildDate).toBe("string");
        // either a real formatted date or the safe fallback
        expect(a.buildDate === "unknown" || a.buildDate.endsWith("UTC")).toBe(
            true,
        );
    });

    it("appVersion is never empty (fallback covers missing define)", () => {
        expect(appVersion().length).toBeGreaterThan(0);
    });
});
