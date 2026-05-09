import { useNavigate } from "react-router-dom";
import { useProjectState } from "../lib/projectState";
import { ThreePreview } from "../components/ThreePreview";

export function Editor() {
    const navigate = useNavigate();
    const { selectedGlbPath } = useProjectState();

    return (
        <div className="container">
            <h2>Editor</h2>
            {selectedGlbPath ? (
                <ThreePreview src={selectedGlbPath} height={400} />
            ) : (
                <p style={{ color: "orange" }}>No model loaded.</p>
            )}
            <p>Apply edits to your model in Blender.</p>
            <button onClick={() => navigate("/preview-pick")}>Back</button>
            {" "}
            <button onClick={() => navigate("/export")}>Next</button>
        </div>
    );
}
