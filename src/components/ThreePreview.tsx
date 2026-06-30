import { Component, Suspense, type ReactNode } from "react";
import { Canvas } from "@react-three/fiber";
import { useGLTF, OrbitControls, Bounds, Center } from "@react-three/drei";
import { convertFileSrc } from "@tauri-apps/api/core";

// CRITICAL: useGLTF() throws when the GLB is missing/unreadable. Without an
// error boundary that throw propagates past <Suspense> and unmounts the whole
// React tree -> blank #0f0f0f screen with no message. This boundary turns any
// load failure into an inline, actionable message instead.
class GltfErrorBoundary extends Component<
    { children: ReactNode; src: string },
    { failed: boolean }
> {
    state = { failed: false };
    static getDerivedStateFromError() {
        return { failed: true };
    }
    componentDidCatch(err: unknown) {
        // eslint-disable-next-line no-console
        console.error("ThreePreview: GLB failed to load", this.props.src, err);
    }
    render() {
        if (this.state.failed) {
            return (
                <div
                    style={{
                        width: "100%",
                        height: "100%",
                        display: "flex",
                        flexDirection: "column",
                        alignItems: "center",
                        justifyContent: "center",
                        textAlign: "center",
                        padding: "1rem",
                        color: "#ff6b6b",
                    }}
                >
                    <p style={{ margin: 0, fontWeight: 700 }}>Could not load the 3D model.</p>
                    <p style={{ fontSize: "0.8rem", color: "#aaa", marginTop: "0.5rem", wordBreak: "break-all" }}>
                        {this.props.src}
                    </p>
                    <p style={{ fontSize: "0.8rem", color: "#aaa", maxWidth: 460 }}>
                        The file is missing or unreadable. If you just applied edits,
                        the edit chain likely failed (see the error message above the
                        viewport) and no model was written — fix that and Apply again.
                    </p>
                </div>
            );
        }
        return this.props.children;
    }
}

function Model({ url }: { url: string }) {
    const { scene } = useGLTF(url);
    return (
        <Bounds fit clip observe margin={1.2}>
            <Center>
                <primitive object={scene} />
            </Center>
        </Bounds>
    );
}

interface ThreePreviewProps {
    src: string;
    height?: number | string;
}

export function ThreePreview({ src, height = 400 }: ThreePreviewProps) {
    const url = convertFileSrc(src);

    return (
        <div style={{ width: "100%", height, position: "relative", background: "#f5f5f5", borderRadius: 12, overflow: "hidden" }}>
            {/* Visible loading hint; the Canvas paints over it once the model
                renders. If load fails, the error boundary replaces everything. */}
            <div
                style={{
                    position: "absolute",
                    inset: 0,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: "#666",
                    fontSize: "0.9rem",
                    pointerEvents: "none",
                }}
            >
                Loading 3D model…
            </div>
            {/* key={url} resets the boundary when the source changes so a prior
                failure doesn't stick across regenerate. */}
            <GltfErrorBoundary key={url} src={src}>
                <Canvas
                    camera={{ position: [0, 0, 5], fov: 45 }}
                    style={{ position: "relative" }}
                    gl={{ alpha: false }}
                >
                    {/* Off-white studio background — matches the wrapper div so
                        the loading hint and canvas blend seamlessly. */}
                    <color attach="background" args={["#f5f5f5"]} />
                    <ambientLight intensity={0.6} />
                    <directionalLight position={[5, 10, 5]} intensity={1} />
                    <Suspense fallback={null}>
                        <Model key={url} url={url} />
                    </Suspense>
                    <OrbitControls makeDefault />
                </Canvas>
            </GltfErrorBoundary>
        </div>
    );
}
