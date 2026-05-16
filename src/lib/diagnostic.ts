/**
 * Phase I Issue #29 — diagnostic payload builder (pure, testable core).
 *
 * The Rust `read_diagnostic_log` command returns the (capped) raw log text;
 * the "last N lines" trim and the human-readable bundle are done here so
 * they can be unit-tested without a Tauri runtime. The thin React glue
 * (AboutDialog "Copy diagnostic" button) only wires invoke → buildDiagnostic
 * → navigator.clipboard.
 */

/** Last `n` lines, ignoring a single trailing blank, newline-style agnostic. */
export function tailLines(text: string, n: number): string[] {
    if (!text) return [];
    const lines = text.split(/\r?\n/);
    // A trailing newline yields a final "" element — not a real line.
    if (lines.length > 0 && lines[lines.length - 1] === "") lines.pop();
    if (n <= 0) return [];
    return lines.slice(-n);
}

export interface DiagnosticInput {
    appName: string;
    version: string;
    buildDate: string;
    logPath: string;
    logText: string;
    project: unknown;
    /** Defaults to 200 (ISSUES.md #29). */
    maxLogLines?: number;
}

export function buildDiagnostic(d: DiagnosticInput): string {
    const lines = tailLines(d.logText, d.maxLogLines ?? 200);
    let projectJson: string;
    try {
        projectJson = JSON.stringify(d.project, null, 2);
    } catch {
        projectJson = "<unserialisable project state>";
    }
    return [
        `${d.appName} diagnostic`,
        `Version: ${d.version}`,
        `Build date: ${d.buildDate}`,
        `Log file: ${d.logPath}`,
        "",
        "--- Project state ---",
        projectJson,
        "",
        `--- Last ${lines.length} log line(s) ---`,
        ...lines,
        "",
    ].join("\n");
}
