interface Props {
    onComplete: () => void;
}

export function Step5Meshy({ onComplete }: Props) {
    return (
        <div>
            <h2>Step 5: Meshy API Key</h2>
            <p>This step will store your Meshy API key. (Implemented in Issue #10)</p>
            <button onClick={onComplete}>Mark complete &amp; Next</button>
        </div>
    );
}
