import { useEffect, useState } from "react";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { listen } from "@tauri-apps/api/event";
import { type Settings, DEFAULT_SETTINGS, readSettings, wizardComplete } from "./lib/settings";
import { Wizard } from "./Wizard";
import { Home } from "./Home";

function AppRoutes({ settings, onWizardDone }: { settings: Settings; onWizardDone: () => void }) {
    const complete = wizardComplete(settings);
    return (
        <Routes>
            <Route path="/wizard" element={<Wizard initialSettings={settings} onDone={onWizardDone} />} />
            <Route path="/" element={complete ? <Home /> : <Navigate to="/wizard" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
    );
}

function App() {
    const [settings, setSettings] = useState<Settings | null>(null);
    const [forceWizard, setForceWizard] = useState(false);

    useEffect(() => {
        readSettings()
            .then(setSettings)
            .catch(() => setSettings(DEFAULT_SETTINGS));
    }, []);

    useEffect(() => {
        let cleanup: (() => void) | undefined;
        listen("run-wizard", () => setForceWizard(true)).then((fn) => {
            cleanup = fn;
        });
        return () => cleanup?.();
    }, []);

    if (settings === null) {
        return <div className="container"><p>Loading...</p></div>;
    }

    const effective: Settings = forceWizard
        ? {
              ...settings,
              wizard: {
                  step_blender: false,
                  step_addon: false,
                  step_socket: false,
                  step_bambu: false,
                  step_meshy: false,
              },
          }
        : settings;

    function handleWizardDone() {
        setForceWizard(false);
        readSettings().then(setSettings).catch(() => {});
    }

    return (
        <HashRouter>
            <AppRoutes settings={effective} onWizardDone={handleWizardDone} />
        </HashRouter>
    );
}

export default App;
