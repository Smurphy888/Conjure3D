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
        const key = STEP_KEYS[step];
        const updated: Settings = {
            ...settings,
            ...updates,
            wizard: { ...settings.wizard, [key]: true },
        };
        setSettings(updated);
        await writeSettings(updated);
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
            {step === 4 && <Step5Meshy {...stepProps} />}
            {step > 0 && (
                <button onClick={goBack} style={{ marginTop: "1rem" }}>
                    Back
                </button>
            )}
        </div>
    );
}
