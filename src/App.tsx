import { useEffect, useState } from "react";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { listen } from "@tauri-apps/api/event";
import { type Settings, DEFAULT_SETTINGS, readSettings, wizardComplete } from "./lib/settings";
import { invokeSidecar } from "./lib/ipc";
import { ProjectProvider } from "./lib/projectState";
import { ConnectionProvider } from "./lib/connectionContext";
import { ConnectionBadge } from "./components/ConnectionBadge";
import { ModelDownloadChip } from "./components/ModelDownloadChip";
import { Wizard } from "./Wizard";
import { Home } from "./Home";
import { NewProject } from "./screens/NewProject";
import { Generate } from "./screens/Generate";
import { PreviewPick } from "./screens/PreviewPick";
import { Editor } from "./screens/Editor";
import { AIEditor } from "./screens/AIEditor";
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
            {/*
              Phase J.3: the AI Editor is the primary editing surface at
              /editor. The slider-based manual UI moves to /editor-manual,
              reachable via the "Advanced (manual)" link in the AI Editor
              header. PreviewPick.tsx and any other "navigate('/editor')"
              caller now lands on the AI Editor by default, matching the
              product's NL-first positioning.
            */}
            <Route path="/editor" element={complete ? <AIEditor /> : <Navigate to="/wizard" replace />} />
            <Route path="/editor-manual" element={complete ? <Editor /> : <Navigate to="/wizard" replace />} />
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
        // Phase J.5: background prefetch of the AI model. Fire-and-forget;
        // the sidecar's downloader is idempotent (calling start while
        // already in progress returns the current status, doesn't spawn
        // a duplicate thread). The ModelDownloadChip handles UX. We
        // ONLY trigger on this explicit "wizard just finished" event,
        // never on subsequent app starts — if the user cancels the
        // download they should not have it re-kicked off automatically;
        // the chip's modal has an explicit Retry button for that.
        invokeSidecar("llm.download_start").catch(() => {
            // Network or sidecar error — the chip will surface the
            // resulting error_phase. Swallowing here is correct because
            // the wizard-done flow has nothing user-facing to show.
        });
    }

    return (
        <HashRouter>
            <ConnectionProvider>
                <ProjectProvider>
                    <AppRoutes settings={effective} onWizardDone={handleWizardDone} />
                    <ConnectionBadge />
                    <ModelDownloadChip />
                </ProjectProvider>
            </ConnectionProvider>
        </HashRouter>
    );
}

export default App;
