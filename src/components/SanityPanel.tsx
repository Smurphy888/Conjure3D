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
    return (
        <div style={{
            display: "flex",
            flexWrap: "wrap",
            gap: "0.75rem",
            padding: "0.5rem 0.75rem",
            background: "#1a1a1a",
            borderRadius: 4,
            marginTop: "0.5rem",
        }}>
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
                            color: ok ? "#4caf50" : "#f44336",
                        }}
                    >
                        <span style={{ fontSize: "0.9rem" }}>{ok ? "●" : "●"}</span>
                        {label}
                    </span>
                );
            })}
            {sanity.dims_mm && (
                <span style={{ fontSize: "0.75rem", color: "#888", marginLeft: "auto" }}>
                    {sanity.dims_mm.map((d) => d.toFixed(1)).join(" × ")} mm
                </span>
            )}
        </div>
    );
}
