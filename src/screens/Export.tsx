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
// Phase K: response from export.threemf — single .3mf path with recipe baked in.
interface ThreemfResult {
    ok: boolean;
    error?: string;
    path?: string;
    size?: number;
    object_count?: number;
    filament_count?: number;
    mode?: string;
    object_type?: string;
}
interface SlicerResult {
    ok: boolean;
    error_code?: "BAMBU_PATH_MISSING" | "BAMBU_PATH_INVALID" | "NO_STL_FILES";
    message?: string;
    pid?: number;
    bambu_path?: string;
}

// Phase K export-format choice. 3MF is the default — it bakes the slicer
// recipe + per-filament-extruder assignments directly into the file so
// the user just hits "Slice" in Bambu. STL stays available as a fallback
// for users who want to apply the recipe manually or share the geometry
// with other slicers that don't speak Bambu's 3MF schema.
type ExportFormat = "threemf" | "stl";

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
    const { name, objectType, colorSplitMode, bisectInChain, editApplied, lastSanity, prebaked3mfPath } = useProjectState();
    const { state: connState } = useConnection();
    const gate = editChainGate(connState);

    const [busy, setBusy] = useState(false);
    const [files, setFiles] = useState<StlFile[] | null>(null);
    const [threemfPath, setThreemfPath] = useState<string | null>(prebaked3mfPath);
    const [threemfInfo, setThreemfInfo] = useState<ThreemfResult | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [launched, setLaunched] = useState(false);
    const [format, setFormat] = useState<ExportFormat>("threemf");

    const longestMm = lastSanity?.dims_mm ? Math.max(...lastSanity.dims_mm) : null;
    const recipeText = recipe(objectType, longestMm);

    const expectedCount =
        bisectInChain ? 2 : colorSplitMode === "none" ? 1 : colorSplitMode === "zebra" ? 2 : 4;

    async function doExport3mf(): Promise<string | null> {
        const r = await invokeSidecar<ThreemfResult>("export.threemf", {
            slug: name,
            mode: colorSplitMode,
            object_type: objectType,
            longest_mm: longestMm ?? undefined,
        });
        if (!r.ok || !r.path) {
            setError(
                `3MF export failed: ${r.error ?? "unknown"}\n\n` +
                    "Export runs on the model currently in Blender — it needs a " +
                    "successful Apply in the Editor first, and Blender connected."
            );
            return null;
        }
        setThreemfPath(r.path);
        setThreemfInfo(r);
        return r.path;
    }

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
            // Phase K: branch on format. Both backends produce file
            // paths that Bambu Studio can open via argv — STL gets a
            // list of one-per-color files; 3MF gets a single path.
            // slicer.launch's `stl_paths` is just "arbitrary model
            // paths to pass on argv" despite the historical name.
            let paths: string[] | null;
            if (format === "threemf") {
                const p = threemfPath ?? (await doExport3mf());
                paths = p ? [p] : null;
            } else {
                const f = files ?? (await doExport());
                paths = f ? f.map((x) => x.path) : null;
            }
            if (!paths) return;
            const s = await invokeSidecar<SlicerResult>("slicer.launch", {
                stl_paths: paths,
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
                Color split: <strong>{colorSplitMode}</strong>. Object type:{" "}
                <strong>{objectType}</strong>.
                {format === "stl" && (
                    <>
                        {" "}Expects <strong>{expectedCount}</strong> STL file
                        {expectedCount > 1 ? "s" : ""}.
                    </>
                )}
            </p>

            {/*
              Phase K format toggle. Defaults to 3MF: that's the "one
              click → printable" path the product is built around. STL
              stays available for users who want the geometry in a
              slicer that doesn't read Bambu's 3MF schema (PrusaSlicer,
              Cura, etc.), or who want to apply the recipe by hand.
            */}
            <div style={{ marginTop: "0.5rem", textAlign: "left", maxWidth: 560, marginInline: "auto" }}>
                <label style={{ display: "block", marginBottom: "0.25rem", fontSize: "0.85rem" }}>
                    Export format
                </label>
                {(["threemf", "stl"] as ExportFormat[]).map((f) => (
                    <label key={f} style={{ display: "block", fontSize: "0.85rem", marginBottom: "0.15rem" }}>
                        <input
                            type="radio"
                            name="export-format"
                            value={f}
                            checked={format === f}
                            onChange={() => {
                                setFormat(f);
                                // Reset prior export state so the user
                                // doesn't accidentally re-launch with
                                // the other format's artefacts.
                                setLaunched(false);
                                setError(null);
                            }}
                            style={{ marginRight: "0.4rem" }}
                        />
                        {f === "threemf" ? (
                            <>
                                <strong>3MF</strong> — recipe baked in
                                <span style={{ color: "#888" }}>
                                    {" "}(one .3mf for Bambu Studio; just hit Slice)
                                </span>
                            </>
                        ) : (
                            <>
                                <strong>STL</strong>
                                <span style={{ color: "#888" }}>
                                    {" "}(one per colour; apply the recipe yourself)
                                </span>
                            </>
                        )}
                    </label>
                ))}
            </div>

            {threemfInfo && format === "threemf" && (
                <div style={{ textAlign: "left", marginTop: "0.5rem" }}>
                    <p style={{ fontWeight: 700 }}>3MF written:</p>
                    <p style={{ fontSize: "0.8rem", wordBreak: "break-all" }}>
                        <code>{threemfInfo.path}</code>
                        <br />
                        {threemfInfo.object_count} object{(threemfInfo.object_count ?? 0) > 1 ? "s" : ""}
                        {", "}
                        {threemfInfo.filament_count} filament{(threemfInfo.filament_count ?? 0) > 1 ? "s" : ""}
                        {threemfInfo.size != null && (
                            <>
                                {", "}{(threemfInfo.size / 1024).toFixed(0)} KB
                            </>
                        )}
                    </p>
                </div>
            )}

            {files && format === "stl" && (
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
                className="btn-primary"
                onClick={handleExportAndSlice}
                disabled={busy || !editApplied || !gate.allowed}
                style={{ marginTop: "0.75rem" }}
            >
                {busy
                    ? "Exporting…"
                    : format === "threemf"
                        ? "Export 3MF & Open in Bambu Studio"
                        : "Export STLs & Open in Bambu Studio"}
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
                    {format === "threemf"
                        ? <>Bambu Studio launched with your .3mf — hit <strong>Slice plate → Print</strong>.</>
                        : <>Bambu Studio launched with your STL{expectedCount > 1 ? "s" : ""}.
                          Now click <strong>Slice plate → Print</strong> in Bambu Studio.</>}
                </p>
            )}

            {format === "threemf" && (
                <div style={{ marginTop: "1rem", textAlign: "left", maxWidth: 560 }}>
                    <p style={{ color: "#2ecc71", fontSize: "0.85rem" }}>
                        ✓ Slicer recipe baked into the .3mf — process, walls,
                        infill, brim, supports{objectType === "vase" ? ", spiral mode" : ""}, and
                        filament assignments are pre-applied. When Bambu opens
                        the file you can hit <strong>Slice plate → Print</strong>{" "}
                        directly.
                    </p>
                </div>
            )}
            <div style={{ marginTop: "1rem", textAlign: "left", maxWidth: 560, display: format === "stl" ? "block" : "none" }}>
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
                {colorSplitMode === "zebra" && (
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
