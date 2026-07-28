import { defineConfig, mergeConfig } from "vitest/config";

import viteConfig from "./vite.config";

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: "happy-dom",
      setupFiles: ["tests/setup.ts"],
      include: ["tests/**/*.spec.ts"],
      coverage: {
        provider: "v8",
        include: ["src/**/*.{ts,vue}"],
        exclude: ["src/main.ts", "src/api/schema.d.ts", "src/vite-env.d.ts"],
        thresholds: {
          lines: 90,
          functions: 90,
          branches: 90,
          statements: 90,
        },
      },
    },
  }),
);
