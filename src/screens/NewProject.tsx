import { useNavigate } from "react-router-dom";
import { useProjectDispatch } from "../lib/projectState";

export function NewProject() {
    const dispatch = useProjectDispatch();
    const navigate = useNavigate();

    function handleNext() {
        navigate("/generate");
    }

    return (
        <div className="container">
            <h2>New Project</h2>
            <p>Name your project and describe what you want to generate.</p>
            <button onClick={() => { dispatch({ type: "RESET" }); navigate("/"); }}>
                Back
            </button>
            <button onClick={handleNext}>Next</button>
        </div>
    );
}
