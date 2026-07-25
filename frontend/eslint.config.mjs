import pluginSecurity from "eslint-plugin-security";
import pluginVue from "eslint-plugin-vue";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: ["dist/**", "coverage/**", "node_modules/**", "src/api/schema.d.ts"],
  },
  ...tseslint.configs.recommended,
  ...pluginVue.configs["flat/recommended"],
  pluginSecurity.configs.recommended,
  {
    files: ["**/*.vue"],
    languageOptions: {
      parserOptions: {
        parser: tseslint.parser,
        extraFileExtensions: [".vue"],
      },
    },
  },
  {
    rules: {
      "vue/multi-word-component-names": "off",
    },
  },
);
