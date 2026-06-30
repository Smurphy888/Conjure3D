import type { Sanity } from "../lib/types";

interface Props {
    sanity: Sanity;
}

const CHECKS: { key: keyof Sanity; label: string }[] = [
    { key: "manifold", label: "Manifold" },
    { key: "single_component", label: "Single component" },
    { key: "normals_outward", label: "Normals outward" },
    { key: "longest_dim_under_limit", label: "Longest dim ≤ 256 mm" },
];

export function SanityPanel({ sanity }: Props) {
    const allOk = CHECKS.every(({ key }) => sanity[key] as boolean);
    return (
        <div
            style={{
                display: "flex",
                flexWrap: "wrap",
                gap: "0.5rem 1rem",
                padding: "0.6rem 0.8rem",
                background: "var(--surface)",
                border: `1px solid ${allOk ? "var(--border)" : "var(--danger)"}`,
                borderRadius: "var(--radius-sm)",
                marginTop: "0.5rem",
            }}
        >
            {CHECKS.map(({ key, label }) => {
                const ok = sanity[key] as boolean;
                return (
                    <span
                        key={key}
                        style={{
                            display: "flex",
                            alignItems: "center",
                            gap: "0.3rem",
                            fontSize: "0.8rem",
                        }}
                    >
                        <span
                            style={{
                                fontWeight: 700,
                                fontSize: "0.9rem",
                                color: ok ? "var(--success)" : "var(--danger)",
                            }}
                        >
                            {ok ? "✓" : "✗"}
                        </span>
                        <span
                            style={{
                                color: ok ? "var(--text-muted)" : "var(--danger)",
                                fontWeight: ok ? 400 : 600,
                            }}
                        >
                            {label}
                        </span>
                    </span>
                );
            })}
            {sanity.dims_mm && (
                <span style={{ fontSize: "0.75rem", color: "var(--text-faint)", marginLeft: "auto" }}>
                    {sanity.dims_mm.map((d) => d.toFixed(1)).join(" × ")} mm
                </span>
            )}
        </div>
    );
}
