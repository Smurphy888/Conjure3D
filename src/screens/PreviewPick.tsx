import { useNavigate } from "react-router-dom";

export function PreviewPick() {
    const navigate = useNavigate();

    return (
        <div className="container">
            <h2>Pick a Preview</h2>
            <p>Choose the generated model you want to refine.</p>
            <button onClick={() => navigate("/generate")}>Back</button>
            <button onClick={() => navigate("/editor")}>Next</button>
        </div>
    );
}
