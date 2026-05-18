import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useProjectState, useProjectDispatch } from "../lib/projectState";
import { ThreePreview } from "../components/ThreePreview";
import { SanityPanel } from "../components/SanityPanel";
import { invokeSidecar } from "../lib/ipc";
import { useConnection } from "../lib/connectionContext";
import { editChainGate } from "../lib/blenderConnection";
import { buildEdits, shouldWarnColorSplit, DEFAULT_PARAMS, type EditorParams, type ObjectType, type ColorSplitMode } from "../lib/edits";
import type { EditChainResult } from "../lib/types";

export function Editor() {
    const navigate = useNavigate();
    const { selectedGlbPath, lastSanity } = useProjectState();
    const dispatch = useProjectDispatch();
    const { state: connState } = useConnection();
    const gate = editChainGate(connState);

    const [params, setParams] = useState<EditorParams>({ ...DEFAULT_PARAMS });
    const [applying, setApplying] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [applyVersion, setApplyVersion] = useState(0);
    const [currentGlbPath, setCurrentGlbPath] = useState(selectedGlbPath);

    const showColorSplitWarning = shouldWarnColorSplit(params);

    function set<K extends keyof EditorParams>(key: K, val: EditorParams[K]) {
        setParams((p) => ({ ...p, [key]: val }));
    }

    async function handleApply() {
        if (!currentGlbPath) return;
        if (!gate.allowed) {
            setError(gate.message);
            return;
        }
        setApplying(true);
        setError(null);
        try {
            const edits = buildEdits(params);
            const result = await invokeSidecar<EditChainResult>("edit.apply_chain", {
                src_glb: currentGlbPath,
                edits,
                dst_dir: "",
            });
            // The orchestrator NEVER raises across JSON-RPC: it returns a
            // preview_glb PATH plus errors[] even when nothing was written
            // (e.g. Blender socket down -> "import failed: ..."). Trusting
            // preview_glb blindly = trying to load a file that doesn't exist
            // -> the misleading "could not load model". Surface errors and
            // keep the previous good model instead of swapping to a path
            // that was never produced.
            if (result.errors && result.errors.length > 0) {
                if (result.sanity) dispatch({ type: "SET_SANITY", lastSanity: result.sanity });
                setError(
                    "Edit chain failed — model NOT updated:\n• " +
                        result.errors.join("\n• ") +
                        "\n\n(Most common cause: Blender isn't connected. Open Blender, " +
                        "click “Connect to Claude” in the BlenderMCP panel, wait for the " +
                        "badge to go green, then Apply again.)"
                );
                return;
            }
            dispatch({ type: "SET_EDITS", edits });
            dispatch({ type: "SET_SANITY", lastSanity: result.sanity });
            setCurrentGlbPath(result.preview_glb);
            dispatch({ type: "SET_GLB_PATH", selectedGlbPath: result.preview_glb });
            setApplyVersion((v) => v + 1);
        } catch (e) {
            setError(String(e));
        } finally {
            setApplying(false);
        }
    }

    const sanityOk = lastSanity
        ? lastSanity.manifold && lastSanity.single_component && lastSanity.normals_outward && lastSanity.longest_dim_under_limit
        : true;

    return (
        <div className="container">
            <h2>Editor</h2>

            <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
                {/* Parameter panel */}
                <div style={{ flex: "0 0 240px" }}>
                    <div style={{ marginBottom: "0.75rem" }}>
                        <label>Object type</label>
                        <select
                            value={params.object_type}
                            onChange={(e) => set("object_type", e.target.value as ObjectType)}
                            style={{ display: "block", width: "100%", marginTop: "0.25rem" }}
                        >
                            <option value="vase">Vase</option>
                            <option value="solid_decorative">Solid decorative</option>
                            <option value="flat_part">Flat part</option>
                        </select>
                    </div>

                    <div style={{ marginBottom: "0.75rem" }}>
                        <label>Target height (mm)</label>
                        <input
                            type="number"
                            min={10}
                            max={250}
                            value={params.target_height_mm}
                            onChange={(e) => set("target_height_mm", Number(e.target.value))}
                            style={{ display: "block", width: "100%", marginTop: "0.25rem" }}
                        />
                    </div>

                    <div style={{ marginBottom: "0.75rem" }}>
                        <label>
                            <input
                                type="checkbox"
                                checked={params.flat_bottom}
                                onChange={(e) => set("flat_bottom", e.target.checked)}
                                style={{ marginRight: "0.4rem" }}
                            />
                            Flat bottom
                        </label>
                    </div>

                    <div style={{ marginBottom: "0.75rem" }}>
                        <label>Max faces (decimate)</label>
                        <input
                            type="number"
                            min={5000}
                            max={500000}
                            step={5000}
                            value={params.decimate_target_faces}
                            onChange={(e) => set("decimate_target_faces", Number(e.target.value))}
                            style={{ display: "block", width: "100%", marginTop: "0.25rem" }}
                        />
                    </div>

                    <div style={{ marginBottom: "0.75rem" }}>
                        <label>Color split</label>
                        {(["none", "zebra", "quarter"] as ColorSplitMode[]).map((m) => (
                            <label key={m} style={{ display: "block", marginTop: "0.2rem" }}>
                                <input
                                    type="radio"
                                    name="color_split"
                                    value={m}
                                    checked={params.color_split_mode === m}
                                    onChange={() => set("color_split_mode", m)}
                                    style={{ marginRight: "0.35rem" }}
                                />
                                {m === "none" ? "None" : m.charAt(0).toUpperCase() + m.slice(1)}
                            </label>
                        ))}
                        {params.color_split_mode === "zebra" && (
                            <div style={{ marginTop: "0.4rem" }}>
                                <label>Band count</label>
                                <input
                                    type="number"
                                    min={2}
                                    max={16}
                                    value={params.color_split_count}
                                    onChange={(e) => set("color_split_count", Number(e.target.value))}
                                    style={{ display: "block", width: "100%", marginTop: "0.2rem" }}
                                />
                            </div>
                        )}
                        {showColorSplitWarning && (
                            <p style={{ color: "#f5a623", fontSize: "0.75rem", marginTop: "0.4rem" }}>
                                Parametric splits work best on rotationally-symmetric objects (vases, lampshades).
                                For complex anatomies, select None and use Bambu Studio's brush paint instead.
                            </p>
                        )}
                    </div>

                    <button
                        onClick={handleApply}
                        disabled={applying || !currentGlbPath || !gate.allowed}
                        style={{ width: "100%" }}
                    >
                        {applying ? "Applying…" : "Apply"}
                    </button>
                    {!gate.allowed && gate.message && (
                        <p style={{ color: "#f5a623", fontSize: "0.8rem", marginTop: "0.4rem" }}>
                            {gate.message}
                        </p>
                    )}
                    {error && <p style={{ color: "red", fontSize: "0.8rem", marginTop: "0.4rem" }}>{error}</p>}
                </div>

                {/* Viewport */}
                <div style={{ flex: 1, minWidth: 300 }}>
                    {currentGlbPath ? (
                        <ThreePreview key={applyVersion} src={currentGlbPath} height={400} />
                    ) : (
                        <p style={{ color: "orange" }}>No model loaded.</p>
                    )}
                    {lastSanity && <SanityPanel sanity={lastSanity} />}
                </div>
            </div>

            <div style={{ marginTop: "1rem" }}>
                <button onClick={() => navigate("/preview-pick")}>Back</button>
                {" "}
                <button onClick={() => navigate("/export")} disabled={!sanityOk}>
                    Next (Export)
                </button>
            </div>
        </div>
    );
}
