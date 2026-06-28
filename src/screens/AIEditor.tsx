/**
 * AI Editor — Phase J.3 primary editing surface.
 *
 * Flow:
 *   1. User types a free-form description ("80mm vase in red and yellow").
 *   2. Click "Generate plan" -> sidecar's llm.generate_chain returns a
 *      validated edit chain (J.1 schema + J.2 mocked backend; J.4 swaps
 *      in real llama.cpp without touching this file).
 *   3. Chain is rendered as a list of editable op-cards. User can tweak
 *      parameters, remove ops, or add ops manually.
 *   4. "Apply" runs edit.apply_chain against the current GLB — same path
 *      the manual Editor uses, same orchestrator, same sanity surface.
 *
 * Manual mode escape hatch: a header link routes to /editor (the
 * existing slider-based UI). Both screens share the viewport and the
 * SanityPanel via component reuse.
 *
 * IMPORTANT: the orchestrator NEVER raises across JSON-RPC. A failed
 * chain returns {errors: [...]} alongside a preview_glb PATH that may
 * not exist on disk. We mirror Editor.tsx's pattern: on errors[],
 * surface them and DO NOT swap the GLB. Otherwise ThreePreview will
 * try to load a file that was never produced and show "could not load
 * model" — a misleading symptom that hides the real cause.
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useProjectState, useProjectDispatch } from "../lib/projectState";
import { ThreePreview } from "../components/ThreePreview";
import { SanityPanel } from "../components/SanityPanel";
import { invokeSidecar } from "../lib/ipc";
import { useConnection } from "../lib/connectionContext";
import { editChainGate } from "../lib/blenderConnection";
import type { Edit, EditChainResult } from "../lib/types";
import type { ObjectType, ColorSplitMode } from "../lib/edits";

interface GenerateChainResult {
    ok: boolean;
    edits?: Edit[];
    backend?: string;
    error_code?: "schema_violation" | "backend_error";
    message?: string;
}

interface BackendInfo {
    backend: string;
}

// ── Op-card metadata: friendly labels + editable fields per op type ──────────

interface FieldSpec {
    key: string;
    label: string;
    min?: number;
    max?: number;
    step?: number;
    /** "select" gets a <select> instead of <input type="number"> */
    options?: readonly string[];
}

interface OpSpec {
    type: string;
    label: string;
    fields: FieldSpec[];
    /** What gets appended to the chain when the user clicks "+ Add op". */
    defaults: Edit;
}

// The 10 canonical ops. Adding an op type elsewhere (Pydantic schema,
// orchestrator, GBNF) and forgetting to add it here means the AI Editor
// can't render or add it manually — a silent feature gap.
const OP_SPECS: readonly OpSpec[] = [
    {
        type: "scale_to_longest",
        label: "Scale to longest dim",
        fields: [{ key: "target_mm", label: "Target (mm)", min: 1, max: 300, step: 1 }],
        defaults: { type: "scale_to_longest", target_mm: 80 },
    },
    {
        type: "voxel_remesh",
        label: "Voxel remesh (watertight)",
        fields: [{ key: "voxel_mm", label: "Voxel size (mm)", min: 0.1, max: 10, step: 0.1 }],
        defaults: { type: "voxel_remesh", voxel_mm: 0.8 },
    },
    { type: "keep_largest", label: "Keep largest component", fields: [], defaults: { type: "keep_largest" } },
    { type: "recenter_xy", label: "Recenter on X/Y", fields: [], defaults: { type: "recenter_xy" } },
    {
        type: "flat_bottom",
        label: "Flatten bottom",
        fields: [{ key: "cut_mm", label: "Cut depth (mm)", min: 0.1, max: 20, step: 0.1 }],
        defaults: { type: "flat_bottom", cut_mm: 1 },
    },
    { type: "fix_normals", label: "Fix normals (outward)", fields: [], defaults: { type: "fix_normals" } },
    {
        type: "decimate",
        label: "Decimate (reduce faces)",
        fields: [{ key: "target_faces", label: "Target faces", min: 1000, max: 500000, step: 1000 }],
        defaults: { type: "decimate", target_faces: 50000 },
    },
    {
        type: "open_top",
        label: "Open top (vase)",
        fields: [{ key: "cut_mm", label: "Cut depth (mm)", min: 0.1, max: 30, step: 0.1 }],
        defaults: { type: "open_top", cut_mm: 2 },
    },
    { type: "bridge_top_loops", label: "Bridge top loops (vase)", fields: [], defaults: { type: "bridge_top_loops" } },
    {
        type: "color_split",
        label: "Color split (multi-filament)",
        fields: [
            { key: "mode", label: "Mode", options: ["none", "zebra", "quarter"] },
            { key: "count", label: "Count", min: 2, max: 32, step: 1 },
        ],
        defaults: { type: "color_split", mode: "zebra", count: 8 },
    },
];

function specFor(type: string): OpSpec | undefined {
    return OP_SPECS.find((s) => s.type === type);
}

// ── Op-card component ───────────────────────────────────────────────────────

interface OpCardProps {
    edit: Edit;
    index: number;
    onChange: (next: Edit) => void;
    onRemove: () => void;
}

function OpCard({ edit, index, onChange, onRemove }: OpCardProps) {
    const spec = specFor(edit.type);
    if (!spec) {
        // The LLM emitted an unknown type. Pydantic should have rejected
        // it server-side; if it didn't, surface visibly rather than
        // silently dropping the op.
        return (
            <div style={{ ...cardStyle, borderColor: "#c33" }}>
                <strong>{index + 1}.</strong>{" "}
                <span style={{ color: "#c33" }}>Unknown op: {edit.type}</span>
                <button onClick={onRemove} style={removeBtnStyle}>×</button>
            </div>
        );
    }
    return (
        <div style={cardStyle}>
            <div style={{ display: "flex", alignItems: "baseline", gap: "0.5rem" }}>
                <strong>{index + 1}.</strong>
                <span style={{ flex: 1 }}>{spec.label}</span>
                <button onClick={onRemove} style={removeBtnStyle} title="Remove this op">×</button>
            </div>
            {spec.fields.length > 0 && (
                <div style={{ marginTop: "0.5rem", display: "grid", gap: "0.35rem" }}>
                    {spec.fields.map((f) => (
                        <div key={f.key} style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "0.5rem", alignItems: "center" }}>
                            <label style={{ fontSize: "0.85rem" }}>{f.label}</label>
                            {f.options ? (
                                <select
                                    value={String(edit[f.key] ?? "")}
                                    onChange={(e) => onChange({ ...edit, [f.key]: e.target.value })}
                                >
                                    {f.options.map((opt) => (
                                        <option key={opt} value={opt}>{opt}</option>
                                    ))}
                                </select>
                            ) : (
                                <input
                                    type="number"
                                    min={f.min}
                                    max={f.max}
                                    step={f.step ?? 1}
                                    value={Number(edit[f.key] ?? 0)}
                                    onChange={(e) =>
                                        onChange({ ...edit, [f.key]: Number(e.target.value) })
                                    }
                                />
                            )}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

// ── Inline styles (kept local — the rest of the app uses inline styling) ────

const cardStyle: React.CSSProperties = {
    border: "1px solid #444",
    borderRadius: 4,
    padding: "0.5rem 0.6rem",
    background: "rgba(255,255,255,0.03)",
};
const removeBtnStyle: React.CSSProperties = {
    background: "transparent",
    border: "none",
    color: "#aaa",
    fontSize: "1.1rem",
    cursor: "pointer",
    padding: 0,
    lineHeight: 1,
};

// ── Main screen ─────────────────────────────────────────────────────────────

export function AIEditor() {
    const navigate = useNavigate();
    const { selectedGlbPath, lastSanity } = useProjectState();
    const dispatch = useProjectDispatch();
    const { state: connState } = useConnection();
    const gate = editChainGate(connState);

    const [prompt, setPrompt] = useState("");
    const [objectType, setObjectType] = useState<ObjectType>("vase");
    const [chain, setChain] = useState<Edit[]>([]);
    const [generating, setGenerating] = useState(false);
    const [applying, setApplying] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [hint, setHint] = useState<string | null>(null);
    const [backendName, setBackendName] = useState<string>("loading…");
    const [currentGlbPath, setCurrentGlbPath] = useState(selectedGlbPath);
    const [applyVersion, setApplyVersion] = useState(0);

    // Show the backend badge ("Powered by …") so the user knows whether
    // they're talking to the mock, local llama.cpp, or a remote API.
    useEffect(() => {
        invokeSidecar<BackendInfo>("llm.backend_info")
            .then((r) => setBackendName(r.backend))
            .catch(() => setBackendName("unavailable"));
    }, []);

    async function handleGenerate() {
        setGenerating(true);
        setError(null);
        setHint(null);
        try {
            const res = await invokeSidecar<GenerateChainResult>("llm.generate_chain", {
                user_prompt: prompt,
                object_type: objectType,
                sanity: lastSanity ?? undefined,
            });
            if (!res.ok) {
                setError(res.message ?? "Plan generation failed.");
                if (res.error_code === "schema_violation") {
                    setHint(
                        "The AI returned something we couldn't validate. " +
                            "Try rephrasing your request, or build the chain manually."
                    );
                } else if (res.error_code === "backend_error") {
                    setHint(
                        "The local AI model isn't ready (try again later, or " +
                            "fall back to manual editing while the model loads)."
                    );
                }
                return;
            }
            setChain(res.edits ?? []);
        } catch (e) {
            setError(`Could not reach the sidecar: ${String(e)}`);
        } finally {
            setGenerating(false);
        }
    }

    function updateOp(i: number, next: Edit) {
        setChain((c) => c.map((e, idx) => (idx === i ? next : e)));
    }

    function removeOp(i: number) {
        setChain((c) => c.filter((_, idx) => idx !== i));
    }

    function addOp(type: string) {
        const spec = specFor(type);
        if (!spec) return;
        setChain((c) => [...c, { ...spec.defaults }]);
    }

    async function handleApply() {
        if (!currentGlbPath) return;
        if (chain.length === 0) {
            setError("No edits to apply — generate a plan or add ops manually first.");
            return;
        }
        if (!gate.allowed) {
            setError(gate.message);
            return;
        }
        setApplying(true);
        setError(null);
        setHint(null);
        try {
            const result = await invokeSidecar<EditChainResult>("edit.apply_chain", {
                src_glb: currentGlbPath,
                edits: chain,
                dst_dir: "",
            });
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
            dispatch({ type: "SET_EDITS", edits: chain });
            dispatch({ type: "SET_SANITY", lastSanity: result.sanity });
            // Best-effort: derive object_type + color_split_mode for downstream
            // screens (Export uses these for the recipe). If chain has no
            // color_split edit, fall back to "none".
            const hasOpenTop = chain.some((e) => e.type === "open_top");
            const cs = chain.find((e) => e.type === "color_split");
            dispatch({
                type: "SET_EDIT_META",
                objectType: hasOpenTop ? "vase" : objectType === "vase" ? "solid_decorative" : objectType,
                colorSplitMode: (cs?.mode as ColorSplitMode | undefined) ?? "none",
                prebaked3mfPath: result.threemf_path ?? null,
            });
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
            <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
                <h2 style={{ margin: 0 }}>AI Editor</h2>
                <span style={{ fontSize: "0.8rem", color: "#888" }}>
                    Powered by: <code>{backendName}</code>{" "}
                    <button
                        onClick={() => navigate("/editor-manual")}
                        style={{ ...linkBtnStyle, marginLeft: "0.5rem" }}
                        title="Switch to advanced manual editing"
                    >
                        Advanced (manual)
                    </button>
                </span>
            </div>

            {/*
              The global `.container > div { width: min(640px, 100%) }` rule
              caps every direct child at 640 px — fine for Home / Wizard, too
              tight for this two-pane layout (360 px left + min 300 px right +
              gap doesn't fit). Override here so the panels sit side-by-side
              instead of wrapping (which made the page taller than the
              viewport and pushed Back / Next off-screen during J.3 dogfood).
              `width: min(1100px, 100%)` keeps the layout readable on small
              windows and uses full width on larger ones.
            */}
            <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", marginTop: "1rem", width: "min(1100px, 100%)" }}>
                {/* Left panel: NL prompt + plan editor */}
                <div style={{ flex: "0 0 360px" }}>
                    <label style={{ fontSize: "0.85rem" }}>Describe your edits</label>
                    <textarea
                        value={prompt}
                        onChange={(e) => setPrompt(e.target.value)}
                        placeholder="e.g. Make it a vase, 80 mm tall, watertight, split into 8 zebra colors."
                        rows={4}
                        style={{ display: "block", width: "100%", marginTop: "0.25rem", marginBottom: "0.5rem" }}
                    />

                    <div style={{ marginBottom: "0.5rem" }}>
                        <label style={{ fontSize: "0.85rem" }}>Object type</label>
                        <select
                            value={objectType}
                            onChange={(e) => setObjectType(e.target.value as ObjectType)}
                            style={{ display: "block", width: "100%", marginTop: "0.25rem" }}
                        >
                            <option value="vase">Vase</option>
                            <option value="solid_decorative">Solid decorative</option>
                            <option value="flat_part">Flat part</option>
                        </select>
                    </div>

                    <button
                        onClick={handleGenerate}
                        disabled={generating}
                        style={{ width: "100%" }}
                    >
                        {generating ? "Generating plan…" : "Generate plan"}
                    </button>

                    <div style={{ marginTop: "1rem", borderTop: "1px solid #333", paddingTop: "0.75rem" }}>
                        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: "0.5rem" }}>
                            <strong>Plan ({chain.length} {chain.length === 1 ? "step" : "steps"})</strong>
                            <select
                                value=""
                                onChange={(e) => {
                                    if (e.target.value) {
                                        addOp(e.target.value);
                                        e.target.value = "";
                                    }
                                }}
                                style={{ fontSize: "0.8rem" }}
                            >
                                <option value="">+ Add op…</option>
                                {OP_SPECS.map((s) => (
                                    <option key={s.type} value={s.type}>{s.label}</option>
                                ))}
                            </select>
                        </div>
                        {chain.length === 0 && (
                            <p style={{ color: "#888", fontSize: "0.85rem" }}>
                                No plan yet. Generate one above, or add ops manually.
                            </p>
                        )}
                        <div style={{ display: "grid", gap: "0.4rem" }}>
                            {chain.map((edit, i) => (
                                <OpCard
                                    key={`${edit.type}-${i}`}
                                    edit={edit}
                                    index={i}
                                    onChange={(next) => updateOp(i, next)}
                                    onRemove={() => removeOp(i)}
                                />
                            ))}
                        </div>

                        <button
                            onClick={handleApply}
                            disabled={applying || !currentGlbPath || !gate.allowed || chain.length === 0}
                            style={{ width: "100%", marginTop: "0.75rem" }}
                        >
                            {applying ? "Applying…" : "Apply chain"}
                        </button>
                        {!gate.allowed && gate.message && (
                            <p style={{ color: "#f5a623", fontSize: "0.8rem", marginTop: "0.4rem" }}>{gate.message}</p>
                        )}
                        {error && (
                            <p style={{ color: "red", fontSize: "0.8rem", marginTop: "0.4rem", whiteSpace: "pre-wrap" }}>{error}</p>
                        )}
                        {hint && (
                            <p style={{ color: "#f5a623", fontSize: "0.8rem", marginTop: "0.4rem" }}>{hint}</p>
                        )}
                    </div>
                </div>

                {/* Right panel: viewport + sanity */}
                <div style={{ flex: 1, minWidth: 300 }}>
                    {currentGlbPath ? (
                        <ThreePreview key={applyVersion} src={currentGlbPath} height={400} />
                    ) : (
                        <p style={{ color: "orange" }}>No model loaded.</p>
                    )}
                    {lastSanity && <SanityPanel sanity={lastSanity} />}
                </div>
            </div>

            {/*
              Sticky bottom nav — Back / Next stay visible at the bottom of
              the viewport no matter how tall the chain panel grows. This is
              belt-and-braces: even after the styles.css overflow fix lets
              the page scroll properly, the user shouldn't have to hunt for
              the primary navigation. The right padding leaves clearance
              for the fixed connection badge at bottom-right.
            */}
            <div
                style={{
                    position: "sticky",
                    bottom: 0,
                    marginTop: "1rem",
                    padding: "0.75rem 0",
                    paddingRight: "10rem",
                    background: "linear-gradient(to top, rgba(15,15,15,1) 70%, rgba(15,15,15,0))",
                    width: "min(1100px, 100%)",
                    zIndex: 50,
                }}
            >
                <button onClick={() => navigate("/preview-pick")}>Back</button>
                {" "}
                <button onClick={() => navigate("/export")} disabled={!sanityOk}>
                    Next (Export)
                </button>
            </div>
        </div>
    );
}

const linkBtnStyle: React.CSSProperties = {
    background: "none",
    border: "none",
    color: "#7af",
    cursor: "pointer",
    textDecoration: "underline",
    padding: 0,
    font: "inherit",
};
