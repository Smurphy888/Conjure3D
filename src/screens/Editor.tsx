import { useNavigate } from "react-router-dom";

export function Editor() {
    const navigate = useNavigate();

    return (
        <div className="container">
            <h2>Editor</h2>
            <p>Apply edits to your model in Blender.</p>
            <button onClick={() => navigate("/preview-pick")}>Back</button>
            <button onClick={() => navigate("/export")}>Next</button>
        </div>
    );
}
