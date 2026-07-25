import { ref } from "vue";

const STORAGE_KEY = "blink-theme";
const DARK_CLASS = "blink-dark";

const isDark = ref(true);

function apply(): void {
  document.documentElement.classList.toggle(DARK_CLASS, isDark.value);
}

export function initTheme(): void {
  isDark.value = localStorage.getItem(STORAGE_KEY) !== "light";
  apply();
}

export function useTheme() {
  function setDark(value: boolean): void {
    isDark.value = value;
    localStorage.setItem(STORAGE_KEY, value ? "dark" : "light");
    apply();
  }

  function toggle(): void {
    setDark(!isDark.value);
  }

  return { isDark, setDark, toggle };
}
