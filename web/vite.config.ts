/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API server (packtherm serve) serves the built app at /, so every API
// call is same-origin. In development, `npm run dev` proxies the API paths to
// a local server on port 8000.
const API = ["/health", "/limits", "/schema", "/template", "/cells", "/studies", "/docs", "/openapi.json"];

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/packtherm/web_static",
    emptyOutDir: true,
  },
  server: {
    proxy: Object.fromEntries(API.map((p) => [p, "http://127.0.0.1:8000"])),
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
  },
});
