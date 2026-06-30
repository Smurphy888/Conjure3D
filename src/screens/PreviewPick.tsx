import { useNavigate } from "react-router-dom";
import { useProjectState } from "../lib/projectState";
import { ThreePreview } from "../components/ThreePreview";

export function PreviewPick() {
    const navigate = useNavigate();
    const { selectedGlbPath, previewTaskId } = useProjectState();

    return (
        <div className="container">
            <h2>Pick a Preview</h2>
            {selectedGlbPath ? (
                <>
                    <ThreePreview src={selectedGlbPath} height={400} />
                    <p style={{ fontSize: "0.8rem", color: "#888" }}>{selectedGlbPath}</p>
                </>
            ) : (
                <p style={{ color: "orange" }}>No model loaded yet.</p>
            )}
            {previewTaskId && <p>Task ID: {previewTaskId}</p>}
            <button onClick={() => navigate("/generate")}>Regenerate</button>
            {" "}
            <button className="btn-primary" onClick={() => navigate("/editor")} disabled={!selectedGlbPath}>
                Accept &amp; Edit
            </button>
        </div>
    );
}
