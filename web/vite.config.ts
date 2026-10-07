import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Dev server proxies the API and media to uvicorn (`uvicorn api.main:app --port 8000`).
const API = process.env.MIXING_LAB_API ?? "http://127.0.0.1:8000";

export default defineConfig({
  base: "/app/",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": API,
      "/vimages": API,
      "/vassets": API,
    },
  },
  test: {
    environment: "jsdom",
  },
});
