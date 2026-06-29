import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type { Settings, WizardState } from "./lib/settings";
import { writeSettings } from "./lib/settings";
import { Step1Blender } from "./WizardSteps/Step1Blender";
import { Step2Addon } from "./WizardSteps/Step2Addon";
import { Step3Socket } from "./WizardSteps/Step3Socket";
import { Step4Bambu } from "./WizardSteps/Step4Bambu";
import { Step5Meshy } from "./WizardSteps/Step5Meshy";

const STEP_COUNT = 5;

const STEP_KEYS: (keyof WizardState)[] = [
    "step_blender",
    "step_addon",
    "step_socket",
    "step_bambu",
    "step_meshy",
];

interface Props {
    initialSettings: Settings;
    onDone?: () => void;
}

export function Wizard({ initialSettings, onDone }: Props) {
    const navigate = useNavigate();
    const [settings, setSettings] = useState<Settings>(initialSettings);
    const [step, setStep] = useState(() => {
        const w = initialSettings.wizard;
        const firstIncomplete = STEP_KEYS.findIndex((k) => !w[k]);
        return firstIncomplete === -1 ? 0 : firstIncomplete;
    });

    async function markComplete(updates?: Partial<Omit<Settings, "version" | "wizard">>) {
        // Defensive: a step wired as onClick={onComplete} passes a React
        // SyntheticEvent here. Spreading it would inject DOM nodes / circular
        // refs into the settings object, making writeSettings' JSON-serialize
        // throw — the await then rejects and the wizard silently never
        // advances. Only accept a plain settings-shaped object.
        const safeUpdates =
            updates &&
            typeof updates === "object" &&
            !("nativeEvent" in updates) &&
            !("_reactName" in updates)
                ? updates
                : undefined;

        const key = STEP_KEYS[step];
        const updated: Settings = {
            ...settings,
            ...safeUpdates,
            wizard: { ...settings.wizard, [key]: true },
        };
        try {
            setSettings(updated);
            await writeSettings(updated);
        } catch (e) {
            // Surface instead of silently freezing on Step N.
            // eslint-disable-next-line no-console
            console.error("markComplete: writeSettings failed", e);
            window.alert(
                `Could not save setup progress: ${String(e)}\n\n` +
                    "Your Blender/Meshy detection still worked; this is a settings-write error."
            );
            return;
        }
        if (step < STEP_COUNT - 1) {
            setStep(step + 1);
        } else {
            onDone?.();
            navigate("/");
        }
    }

    function goBack() {
        if (step > 0) setStep(step - 1);
    }

    const stepProps = { onComplete: markComplete };

    return (
        <div className="container">
            <h1>Conjure3D Setup</h1>
            <p>Step {step + 1} of {STEP_COUNT}</p>
            {step === 0 && <Step1Blender {...stepProps} />}
            {step === 1 && <Step2Addon {...stepProps} />}
            {step === 2 && <Step3Socket {...stepProps} />}
            {step === 3 && <Step4Bambu {...stepProps} />}
            {step === 4 && <Step5Meshy {...stepProps} currentProvider={settings.generation_provider ?? "meshy"} />}
            {step > 0 && (
                <button onClick={goBack} style={{ marginTop: "1rem" }}>
                    Back
                </button>
            )}
        </div>
    );
}
