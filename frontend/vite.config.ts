import { fileURLToPath, URL } from "node:url";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";
import istanbul from "vite-plugin-istanbul";

import packageJson from "./package.json" with { type: "json" };

// Instrumented builds are opt-in and never the default `npm run build` (the
// one the production Docker image runs) - only `npm run build:coverage`,
// used solely to measure how much of the app the Playwright e2e suite
// actually exercises. Shipping this to real users would leak an internal
// `window.__coverage__` global and bloat the bundle for no user benefit.
const coverageBuild = process.env.VITE_COVERAGE === "true";

export default defineConfig({
  plugins: [
    vue(),
    ...(coverageBuild
      ? [istanbul({ include: "src/*", exclude: ["node_modules", "tests/"], forceBuildInstrument: true })]
      : []),
  ],
  define: {
    __APP_VERSION__: JSON.stringify(packageJson.version),
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": {
        // In the dev container the backend is reachable as http://backend:8000.
        target: process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8000",
      },
    },
  },
});
