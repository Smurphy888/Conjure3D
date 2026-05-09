import { useNavigate } from "react-router-dom";

export function Generate() {
    const navigate = useNavigate();

    return (
        <div className="container">
            <h2>Generate</h2>
            <p>Generating your 3D model via Meshy…</p>
            <button onClick={() => navigate("/new-project")}>Back</button>
            <button onClick={() => navigate("/preview-pick")}>Next</button>
        </div>
    );
}
