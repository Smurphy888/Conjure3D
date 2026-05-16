/**
 * Phase I Issue #28 — About info (pure, testable core).
 *
 * `__APP_VERSION__` and `__BUILD_DATE__` are injected by Vite `define`
 * (vite.config.ts). Notes that bite future maintainers:
 *  - __BUILD_DATE__ is evaluated when the Vite config *loads*: for
 *    `vite build` that is the build moment; for `pnpm dev` it is whenever
 *    the dev server was started, not "now". That is the correct semantic
 *    for an About box (it reports the build, not the clock).
 *  - version is sourced from package.json. package.json and
 *    tauri.conf.json are both kept at the same value; if they ever drift,
 *    About reflects package.json.
 *  - the `typeof … !== "undefined"` guards are load-bearing: under a bare
 *    vitest/jsdom transform the defines may be absent, and a direct read of
 *    an undeclared global throws. The guard keeps the formatter pure and
 *    testable without mocking the bundler.
 */

export const APP_NAME = "Conjure3D";

export function appVersion(): string {
    return typeof __APP_VERSION__ !== "undefined" ? __APP_VERSION__ : "0.0.0";
}

export function buildDateIso(): string {
    return typeof __BUILD_DATE__ !== "undefined" ? __BUILD_DATE__ : "";
}

/**
 * Format an ISO timestamp as a stable, locale-independent UTC string
 * (`YYYY-MM-DD HH:MM UTC`). Empty/invalid input → "unknown" so the dialog
 * never renders "Invalid Date".
 */
export function formatBuildDate(iso: string): string {
    if (!iso) return "unknown";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "unknown";
    const p = (n: number) => String(n).padStart(2, "0");
    return (
        `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ` +
        `${p(d.getUTCHours())}:${p(d.getUTCMinutes())} UTC`
    );
}

export interface AboutInfo {
    name: string;
    version: string;
    /** Already human-formatted (see formatBuildDate). */
    buildDate: string;
}

export function getAbout(): AboutInfo {
    return {
        name: APP_NAME,
        version: appVersion(),
        buildDate: formatBuildDate(buildDateIso()),
    };
}
