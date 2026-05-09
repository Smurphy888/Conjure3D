import { useNavigate } from "react-router-dom";
import { useProjectState } from "../lib/projectState";

export function PreviewPick() {
    const navigate = useNavigate();
    const { selectedGlbPath, previewTaskId } = useProjectState();

    return (
        <div className="container">
            <h2>Pick a Preview</h2>
            {selectedGlbPath ? (
                <p>
                    Model ready: <code style={{ wordBreak: "break-all" }}>{selectedGlbPath}</code>
                </p>
            ) : (
                <p style={{ color: "orange" }}>No model loaded yet.</p>
            )}
            {previewTaskId && <p>Task ID: {previewTaskId}</p>}
            <button onClick={() => navigate("/generate")}>Regenerate</button>
            {" "}
            <button onClick={() => navigate("/editor")} disabled={!selectedGlbPath}>
                Accept &amp; Edit
            </button>
        </div>
    );
}
