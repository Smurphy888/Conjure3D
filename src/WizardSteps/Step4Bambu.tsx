interface Props {
    onComplete: () => void;
}

export function Step4Bambu({ onComplete }: Props) {
    return (
        <div>
            <h2>Step 4: Bambu Studio</h2>
            <p>This step will detect Bambu Studio. (Implemented in Issue #10)</p>
            <button onClick={onComplete}>Mark complete &amp; Next</button>
        </div>
    );
}
