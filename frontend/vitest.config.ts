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
        // main.ts and App.vue are both thin bootstrap/shell code with no
        // script-level statements of their own (App.vue is <script setup>
        // with two side-effect-free imports and a template that's just
        // three child components) - v8's coverage provider finds zero
        // instrumentable lines/functions/branches in them, which lcov/text
        // reporters render as a misleading "0%" row rather than omitting it
        // outright. Excluding them from the coverage universe only affects
        // this report; app-shell.spec.ts still actually mounts and asserts
        // against App.vue.
        exclude: ["src/main.ts", "src/App.vue", "src/api/schema.d.ts", "src/vite-env.d.ts"],
        reporter: ["text", "html", "lcov", "cobertura"],
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
