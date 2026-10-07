import type { DetailedHTMLProps, HTMLAttributes } from "react";

// <model-viewer> (vendored at /vassets/model-viewer-umd.min.js) as a JSX intrinsic element.
declare module "react" {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace JSX {
    interface IntrinsicElements {
      "model-viewer": DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement> & {
        src: string;
        alt?: string;
        "camera-controls"?: boolean | string;
        "auto-rotate"?: boolean | string;
        "rotation-per-second"?: string;
        "interaction-prompt"?: string;
        "shadow-intensity"?: string;
        exposure?: string;
      };
    }
  }
}
