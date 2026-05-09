interface Props {
    onComplete: () => void;
}

export function Step3Socket({ onComplete }: Props) {
    return (
        <div>
            <h2>Step 3: BlenderMCP Connection</h2>
            <p>This step will test the BlenderMCP socket connection. (Implemented in Issue #9)</p>
            <button onClick={onComplete}>Mark complete &amp; Next</button>
        </div>
    );
}
