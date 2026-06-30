import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useProjectDispatch } from "../lib/projectState";

export function NewProject() {
    const dispatch = useProjectDispatch();
    const navigate = useNavigate();
    const [name, setName] = useState("");
    const [prompt, setPrompt] = useState("");

    function handleStart() {
        if (!name.trim() || !prompt.trim()) return;
        dispatch({ type: "SET_NAME", name: name.trim() });
        dispatch({ type: "SET_PROMPT", prompt: prompt.trim() });
        navigate("/generate");
    }

    return (
        <div className="container">
            <h2>New Project</h2>
            <div style={{ marginBottom: "0.5rem" }}>
                <label>Project name</label>
                <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Geometric vase"
                    style={{ display: "block", width: "100%", marginTop: "0.25rem" }}
                />
            </div>
            <div style={{ marginBottom: "0.5rem" }}>
                <label>Describe what to print</label>
                <textarea
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    rows={4}
                    placeholder="Stylized minimalist geometric vase, single watertight mesh, ~80mm tall."
                    style={{ display: "block", width: "100%", marginTop: "0.25rem" }}
                />
            </div>
            <button onClick={() => navigate("/")}>Back</button>
            {" "}
            <button className="btn-primary" onClick={handleStart} disabled={!name.trim() || !prompt.trim()}>
                Start Generating
            </button>
        </div>
    );
}
