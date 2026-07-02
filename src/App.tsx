import { Component, type ErrorInfo, type ReactNode, useEffect, useRef, useState } from "react";
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
import { Settings as SettingsScreen } from "./screens/Settings";

/**
 * App-wide error boundary. Before this existed, a render throw in ANY screen
 * white-screened the whole app with no recovery path (the only boundary was
 * the local GltfErrorBoundary inside the 3D preview). Class component because
 * React only exposes render-error catching through the class lifecycle.
 *
 * Recovery model: "Try again" clears the boundary and re-renders (enough for
 * transient state bugs); "Restart app" reloads the webview, which re-reads
 * settings and reconnects — the sidecar process is owned by the Rust shell,
 * so it survives the reload.
 */
class AppErrorBoundary extends Component<
    { children: ReactNode },
    { error: Error | null }
> {
    state: { error: Error | null } = { error: null };

    static getDerivedStateFromError(error: Error) {
        return { error };
    }

    componentDidCatch(error: Error, info: ErrorInfo) {
        // The webview console is included in "Copy diagnostic" workflows via
        // DevTools; log the component stack so a field report is actionable.
        console.error("App crashed:", error, info.componentStack);
    }

    render() {
        if (this.state.error === null) return this.props.children;
        return (
            <div className="container" style={{ maxWidth: 560, margin: "4rem auto", textAlign: "center" }}>
                <h1>Something went wrong</h1>
                <p style={{ opacity: 0.85 }}>
                    The screen hit an unexpected error. Your project files on disk are not affected.
                </p>
                <details style={{ textAlign: "left", margin: "1rem 0", opacity: 0.7 }}>
                    <summary>Technical details</summary>
                    <pre style={{ whiteSpace: "pre-wrap", fontSize: "0.8rem" }}>
                        {String(this.state.error?.stack || this.state.error)}
                    </pre>
                </details>
                <div style={{ display: "flex", gap: "0.75rem", justifyContent: "center" }}>
                    <button onClick={() => this.setState({ error: null })}>Try again</button>
                    <button onClick={() => window.location.reload()}>Restart app</button>
                </div>
            </div>
        );
    }
}

function CursorGlow() {
    const ref = useRef<HTMLDivElement>(null);
    useEffect(() => {
        const onMove = (e: MouseEvent) => {
            if (!ref.current) return;
            ref.current.style.left = `${e.clientX}px`;
            ref.current.style.top = `${e.clientY}px`;
        };
        window.addEventListener("mousemove", onMove);
        return () => window.removeEventListener("mousemove", onMove);
    }, []);
    return (
        <div
            ref={ref}
            style={{
                position: "fixed",
                pointerEvents: "none",
                zIndex: 9999,
                width: 380,
                height: 380,
                borderRadius: "50%",
                background: "radial-gradient(circle, rgba(210,160,255,0.15) 0%, rgba(168,85,247,0.05) 45%, transparent 70%)",
                transform: "translate(-50%, -50%)",
                mixBlendMode: "screen",
                left: -9999,
                top: -9999,
            }}
        />
    );
}

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
            <Route path="/settings" element={complete ? <SettingsScreen /> : <Navigate to="/wizard" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
    );
}

function App() {
    const [settings, setSettings] = useState<Settings | null>(null);
    const [forceWizard, setForceWizard] = useState<number | false>(false);

    useEffect(() => {
        readSettings()
            .then(setSettings)
            .catch(() => setSettings(DEFAULT_SETTINGS));
    }, []);

    useEffect(() => {
        let cleanup: (() => void) | undefined;
        listen<{ startAt?: number }>("run-wizard", (e) => setForceWizard(e.payload?.startAt ?? 0)).then((fn) => {
            cleanup = fn;
        });
        return () => cleanup?.();
    }, []);

    if (settings === null) {
        return <div className="container"><p>Loading...</p></div>;
    }

    const effective: Settings = forceWizard !== false
        ? {
              ...settings,
              wizard: {
                  step_blender: forceWizard > 0,
                  step_addon: forceWizard > 1,
                  step_socket: forceWizard > 2,
                  step_bambu: forceWizard > 3,
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
        <AppErrorBoundary>
            <HashRouter>
                <CursorGlow />
                <ConnectionProvider>
                    <ProjectProvider>
                        <AppRoutes settings={effective} onWizardDone={handleWizardDone} />
                        <ConnectionBadge />
                        <ModelDownloadChip />
                    </ProjectProvider>
                </ConnectionProvider>
            </HashRouter>
        </AppErrorBoundary>
    );
}

export default App;
