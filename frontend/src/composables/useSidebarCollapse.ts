import { ref } from "vue";

const STORAGE_KEY = "blink-sidebar-collapsed";

const isCollapsed = ref(localStorage.getItem(STORAGE_KEY) === "true");

export function useSidebarCollapse() {
  function setCollapsed(value: boolean): void {
    isCollapsed.value = value;
    localStorage.setItem(STORAGE_KEY, String(value));
  }

  function toggle(): void {
    setCollapsed(!isCollapsed.value);
  }

  return { isCollapsed, setCollapsed, toggle };
}
