import { useConfirm } from "primevue/useconfirm";

/**
 * One confirmation look for every destructive action in the app (delete a
 * clip, a person, a face sample, a vehicle's protection, ...) so admins get
 * the same danger-styled prompt everywhere rather than each call site
 * inventing its own icon/button wording.
 */
export function useDeleteConfirm() {
  const confirm = useConfirm();

  function confirmDelete(options: {
    header: string;
    message: string;
    acceptLabel?: string;
    onAccept: () => void;
  }): void {
    confirm.require({
      message: options.message,
      header: options.header,
      icon: "pi pi-exclamation-triangle",
      acceptProps: { label: options.acceptLabel ?? "Delete", severity: "danger" },
      rejectProps: { label: "Cancel", severity: "secondary", outlined: true },
      accept: options.onAccept,
    });
  }

  return { confirmDelete };
}
