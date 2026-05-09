import { useEffect, useState } from "react";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { listen } from "@tauri-apps/api/event";
import { type Settings, DEFAULT_SETTINGS, readSettings, wizardComplete } from "./lib/settings";
import { ProjectProvider } from "./lib/projectState";
import { Wizard } from "./Wizard";
import { Home } from "./Home";
import { NewProject } from "./screens/NewProject";
import { Generate } from "./screens/Generate";
import { PreviewPick } from "./screens/PreviewPick";
import { Editor } from "./screens/Editor";
import { Export } from "./screens/Export";

function AppRoutes({ settings, onWizardDone }: { settings: Settings; onWizardDone: () => void }) {
    const complete = wizardComplete(settings);
    return (
        <Routes>
            <Route path="/wizard" element={<Wizard initialSettings={settings} onDone={onWizardDone} />} />
            <Route path="/" element={complete ? <Home /> : <Navigate to="/wizard" replace />} />
            <Route path="/new-project" element={complete ? <NewProject /> : <Navigate to="/wizard" replace />} />
            <Route path="/generate" element={complete ? <Generate /> : <Navigate to="/wizard" replace />} />
            <Route path="/preview-pick" element={complete ? <PreviewPick /> : <Navigate to="/wizard" replace />} />
            <Route path="/editor" element={complete ? <Editor /> : <Navigate to="/wizard" replace />} />
            <Route path="/export" element={complete ? <Export /> : <Navigate to="/wizard" replace />} />
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
            <ProjectProvider>
                <AppRoutes settings={effective} onWizardDone={handleWizardDone} />
            </ProjectProvider>
        </HashRouter>
    );
}

export default App;
