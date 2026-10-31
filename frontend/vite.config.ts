/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Relative asset paths: the server's <base href> puts them under the URL base, if one is set.
  base: "./",
  build: {
    // FastAPI serves the built app from inside the Python package.
    outDir: "../kometa_studio/static",
    emptyOutDir: true,
  },
  server: {
    // `npm run dev` on :5173 talks to `kometa-studio serve` on :8484.
    proxy: { "/api": "http://127.0.0.1:8484" },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
  },
});
