import { useEffect, useState } from "react";

let loading: Promise<void> | null = null;

function loadModelViewer(): Promise<void> {
  if (customElements.get("model-viewer")) return Promise.resolve();
  loading ??= new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "/vassets/model-viewer-umd.min.js";
    script.onload = () => resolve();
    script.onerror = () => {
      loading = null;
      reject(new Error("Could not load the 3D viewer."));
    };
    document.head.appendChild(script);
  });
  return loading;
}

export interface VesselMedia {
  kind: "3d" | "image";
  url: string;
  caption?: string;
}

/** The vessel's 3D model (rotatable) or its best still image. */
export function VesselViewer({ media, name }: { media: VesselMedia; name: string }) {
  const [ready, setReady] = useState(media.kind !== "3d" || !!customElements.get("model-viewer"));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (media.kind !== "3d") return;
    loadModelViewer()
      .then(() => setReady(true))
      .catch((e: Error) => setError(e.message));
  }, [media.kind]);

  if (media.kind === "image") return <img className="vessel-media" src={media.url} alt={name} />;
  if (error) return <p className="error-note">{error}</p>;
  if (!ready) return <p className="muted">Loading 3D viewer…</p>;
  return (
    <model-viewer
      className="vessel-media"
      src={media.url}
      alt={`3D model of ${name}`}
      camera-controls=""
      auto-rotate=""
      rotation-per-second="20deg"
      interaction-prompt="none"
      shadow-intensity="1"
      exposure="1"
    />
  );
}
