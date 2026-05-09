interface Props {
    onComplete: () => void;
}

export function Step1Blender({ onComplete }: Props) {
    return (
        <div>
            <h2>Step 1: Blender Detection</h2>
            <p>This step will detect your Blender installation. (Implemented in Issue #7)</p>
            <button onClick={onComplete}>Mark complete &amp; Next</button>
        </div>
    );
}
