import pluginPlaywright from "eslint-plugin-playwright";
import pluginSecurity from "eslint-plugin-security";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: [
      "playwright-report/**",
      "test-results/**",
      "node_modules/**",
      "playwright/.auth/**",
      "coverage/**",
      ".nyc_output/**",
    ],
  },
  ...tseslint.configs.recommended,
  pluginSecurity.configs.recommended,
  {
    files: ["tests/**/*.ts"],
    ...pluginPlaywright.configs["flat/recommended"],
  },
);
