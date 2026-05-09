import { useNavigate } from "react-router-dom";

export function Export() {
    const navigate = useNavigate();

    return (
        <div className="container">
            <h2>Export</h2>
            <p>Slice and export your model for 3D printing.</p>
            <button onClick={() => navigate("/editor")}>Back</button>
            <button onClick={() => navigate("/")}>Done</button>
        </div>
    );
}
