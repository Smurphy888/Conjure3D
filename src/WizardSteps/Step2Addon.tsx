interface Props {
    onComplete: () => void;
}

export function Step2Addon({ onComplete }: Props) {
    return (
        <div>
            <h2>Step 2: BlenderMCP Addon</h2>
            <p>This step will install the BlenderMCP addon. (Implemented in Issue #8)</p>
            <button onClick={() => onComplete()}>Mark complete &amp; Next</button>
        </div>
    );
}
