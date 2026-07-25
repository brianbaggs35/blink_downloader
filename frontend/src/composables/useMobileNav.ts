import { ref } from "vue";

const isOpen = ref(false);

export function useMobileNav() {
  function open(): void {
    isOpen.value = true;
  }

  function close(): void {
    isOpen.value = false;
  }

  function toggle(): void {
    isOpen.value = !isOpen.value;
  }

  return { isOpen, open, close, toggle };
}
