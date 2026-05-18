import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { invokeSidecar } from "../lib/ipc";
import { useProjectState } from "../lib/projectState";
import { useConnection } from "../lib/connectionContext";
import { editChainGate } from "../lib/blenderConnection";

interface StlFile {
    path: string;
    color: string;
    size: number;
}
interface ExportResult {
    ok: boolean;
    error?: string;
    mode?: string;
    dir?: string;
    count?: number;
    files?: StlFile[];
}
interface SlicerResult {
    ok: boolean;
    error_code?: "BAMBU_PATH_MISSING" | "BAMBU_PATH_INVALID" | "NO_STL_FILES";
    message?: string;
    pid?: number;
    bambu_path?: string;
}

// PROMPT.md § "Shape-aware slicer recipe" — verbatim guidance per object_type.
function recipe(objectType: string, longestMm: number | null): string {
    if (objectType === "vase") {
        return [
            "Process: 0.20mm Standard @BBL X1C",
            "Spiral vase mode = ON  (thin-walled hollow)",
            "  — OR — walls=5, top shell layers=0, infill=0%",
            "Brim: not needed",
            "Supports: OFF",
        ].join("\n");
    }
    if (objectType === "flat_part") {
        return [
            "Process: 0.20mm Standard @BBL X1C",
            "Walls: 4",
            "Infill: 20% gyroid",
            "Top/bottom shells: 4",
            "Brim: 3 mm",
            "Lay flat on the bed (largest face down — auto-orient)",
            "Supports: OFF",
        ].join("\n");
    }
    // solid_decorative (default)
    const brim =
        longestMm != null && longestMm > 100
            ? "Brim: 5 mm  (REQUIRED — longest dim > 100 mm)"
            : "Brim: 5 mm  (recommended if longest dim > 100 mm)";
    return [
        "Process: 0.20mm Standard @BBL X1C",
        "Walls: 3",
        "Infill: 15% gyroid",
        "Top/bottom shells: 4",
        brim,
        "Spiral vase mode = OFF",
        "Supports: OFF  (flat-bottom orientation)",
    ].join("\n");
}

export function Export() {
    const navigate = useNavigate();
    const { name, objectType, colorSplitMode, editApplied, lastSanity } = useProjectState();
    const { state: connState } = useConnection();
    const gate = editChainGate(connState);

    const [busy, setBusy] = useState(false);
    const [files, setFiles] = useState<StlFile[] | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [launched, setLaunched] = useState(false);

    const longestMm = lastSanity?.dims_mm ? Math.max(...lastSanity.dims_mm) : null;
    const recipeText = recipe(objectType, longestMm);

    const expectedCount =
        colorSplitMode === "none" ? 1 : colorSplitMode === "zebra" ? 2 : 8;

    async function doExport(): Promise<StlFile[] | null> {
        const r = await invokeSidecar<ExportResult>("export.stl", {
            slug: name,
            mode: colorSplitMode,
        });
        if (!r.ok || !r.files) {
            setError(
                `STL export failed: ${r.error ?? "unknown"}\n\n` +
                    "Export runs on the model currently in Blender — it needs a " +
                    "successful Apply in the Editor first, and Blender connected."
            );
            return null;
        }
        setFiles(r.files);
        return r.files;
    }

    async function handleExportAndSlice() {
        setBusy(true);
        setError(null);
        setLaunched(false);
        try {
            const f = files ?? (await doExport());
            if (!f) return;
            const s = await invokeSidecar<SlicerResult>("slicer.launch", {
                stl_paths: f.map((x) => x.path),
            });
            if (s.ok) {
                setLaunched(true);
                return;
            }
            if (s.error_code === "BAMBU_PATH_MISSING" || s.error_code === "BAMBU_PATH_INVALID") {
                setError(
                    `Bambu Studio path ${s.error_code === "BAMBU_PATH_MISSING" ? "is not set" : "is invalid"}. ` +
                        "Re-run the setup wizard (View → Re-run Setup Wizard) and complete the Bambu Studio step."
                );
            } else {
                setError(`Slicer launch failed: ${s.message ?? s.error_code ?? "unknown"}`);
            }
        } catch (e) {
            setError(String(e));
        } finally {
            setBusy(false);
        }
    }

    return (
        <div className="container">
            <h2>Export</h2>

            {!editApplied && (
                <p style={{ color: "#f5a623" }}>
                    Apply an edit in the Editor first — Export writes STLs from the
                    model currently in Blender.
                </p>
            )}
            {!gate.allowed && gate.message && (
                <p style={{ color: "#f5a623", fontSize: "0.85rem" }}>{gate.message}</p>
            )}

            <p style={{ fontSize: "0.9rem" }}>
                Color split: <strong>{colorSplitMode}</strong> → expects{" "}
                <strong>{expectedCount}</strong> STL file
                {expectedCount > 1 ? "s" : ""}. Object type:{" "}
                <strong>{objectType}</strong>.
            </p>

            {files && (
                <div style={{ textAlign: "left" }}>
                    <p style={{ fontWeight: 700 }}>STL files written:</p>
                    <ul style={{ fontSize: "0.8rem" }}>
                        {files.map((f) => (
                            <li key={f.path} style={{ wordBreak: "break-all" }}>
                                {f.path} {f.color ? `(${f.color})` : ""} —{" "}
                                {(f.size / 1024).toFixed(0)} KB
                            </li>
                        ))}
                    </ul>
                </div>
            )}

            <button
                onClick={handleExportAndSlice}
                disabled={busy || !editApplied || !gate.allowed}
            >
                {busy ? "Exporting…" : "Export & Open in Bambu Studio"}
            </button>

            {error && (
                <pre
                    style={{
                        color: "#ff6b6b",
                        whiteSpace: "pre-wrap",
                        fontSize: "0.8rem",
                        textAlign: "left",
                        maxWidth: 560,
                    }}
                >
                    {error}
                </pre>
            )}

            {launched && (
                <p style={{ color: "#2ecc71", fontWeight: 700 }}>
                    Bambu Studio launched with your STL{expectedCount > 1 ? "s" : ""}.
                    Now click <strong>Slice plate → Print</strong> in Bambu Studio.
                </p>
            )}

            <div style={{ marginTop: "1rem", textAlign: "left", maxWidth: 560 }}>
                <p style={{ fontWeight: 700, marginBottom: "0.25rem" }}>
                    Slicer recipe ({objectType}) — paste into Bambu Studio:
                </p>
                <pre
                    style={{
                        background: "#161616",
                        border: "1px solid #333",
                        borderRadius: 6,
                        padding: "0.75rem",
                        fontSize: "0.8rem",
                        whiteSpace: "pre-wrap",
                    }}
                >
                    {recipeText}
                </pre>
                <button
                    className="link-button"
                    onClick={() => void navigator.clipboard?.writeText(recipeText)}
                >
                    Copy recipe
                </button>
                {colorSplitMode !== "none" && (
                    <p style={{ fontSize: "0.78rem", color: "#aaa" }}>
                        Multi-color: assign a filament to each STL object in Bambu
                        Studio. Don’t enable spiral vase mode for split parts.
                    </p>
                )}
            </div>

            <div style={{ marginTop: "1rem" }}>
                <button onClick={() => navigate("/editor")}>Back</button>{" "}
                <button onClick={() => navigate("/")}>Done</button>
            </div>
        </div>
    );
}
