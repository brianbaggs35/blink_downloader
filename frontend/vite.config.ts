import { fileURLToPath, URL } from "node:url";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

import packageJson from "./package.json" with { type: "json" };

export default defineConfig({
  plugins: [vue()],
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
