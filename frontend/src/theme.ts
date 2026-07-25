import { definePreset } from "@primeuix/themes";
import Aura from "@primeuix/themes/aura";

// Slate surfaces + cyan primary: calm, dark-first security console.
const slate = {
  50: "#f8fafc",
  100: "#f1f5f9",
  200: "#e2e8f0",
  300: "#cbd5e1",
  400: "#94a3b8",
  500: "#64748b",
  600: "#475569",
  700: "#334155",
  800: "#1e293b",
  900: "#0f172a",
  950: "#020617",
};

export const BlinkPreset = definePreset(Aura, {
  semantic: {
    primary: {
      50: "#ecfeff",
      100: "#cffafe",
      200: "#a5f3fc",
      300: "#67e8f9",
      400: "#22d3ee",
      500: "#06b6d4",
      600: "#0891b2",
      700: "#0e7490",
      800: "#155e75",
      900: "#164e63",
      950: "#083344",
    },
    colorScheme: {
      light: {
        surface: { 0: "#ffffff", ...slate },
      },
      dark: {
        surface: { 0: "#ffffff", ...slate },
      },
    },
  },
});

export const primeVueOptions = {
  theme: {
    preset: BlinkPreset,
    options: {
      darkModeSelector: ".blink-dark",
    },
  },
};
