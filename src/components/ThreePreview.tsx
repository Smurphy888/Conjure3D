import { Suspense } from "react";
import { Canvas } from "@react-three/fiber";
import { useGLTF, OrbitControls, Bounds, Center } from "@react-three/drei";
import { convertFileSrc } from "@tauri-apps/api/core";

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
        <div style={{ width: "100%", height }}>
            <Canvas camera={{ position: [0, 0, 5], fov: 45 }}>
                <ambientLight intensity={0.6} />
                <directionalLight position={[5, 10, 5]} intensity={1} />
                <Suspense fallback={null}>
                    <Model key={url} url={url} />
                </Suspense>
                <OrbitControls makeDefault />
            </Canvas>
        </div>
    );
}
