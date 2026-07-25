/** Timestamps are stored and transmitted as UTC; display always applies the
 * signed-in user's configured timezone (Settings > Profile), never the
 * browser's local zone — those can differ. */

import { useAuthStore } from "@/stores/auth";

const dateTimeCache = new Map<string, Intl.DateTimeFormat>();
const dateCache = new Map<string, Intl.DateTimeFormat>();

function formatterFor(cache: Map<string, Intl.DateTimeFormat>, timeZone: string, dateOnly: boolean) {
  let formatter = cache.get(timeZone);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat(undefined, {
      timeZone,
      dateStyle: "medium",
      timeStyle: dateOnly ? undefined : "short",
    });
    cache.set(timeZone, formatter);
  }
  return formatter;
}

export function useFormatting() {
  const auth = useAuthStore();

  function timezone(): string {
    return auth.user?.timezone || "UTC";
  }

  function formatDateTime(iso: string): string {
    return formatterFor(dateTimeCache, timezone(), false).format(new Date(iso));
  }

  function formatDate(iso: string): string {
    return formatterFor(dateCache, timezone(), true).format(new Date(iso));
  }

  function formatDuration(seconds: number | null): string {
    if (seconds === null) {
      return "—";
    }
    const total = Math.round(seconds);
    const mins = Math.floor(total / 60);
    const secs = total % 60;
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  }

  function formatFileSize(bytes: number | null): string {
    if (bytes === null) {
      return "—";
    }
    if (bytes < 1024) {
      return `${bytes} B`;
    }
    const units = ["KB", "MB", "GB"];
    let value = bytes / 1024;
    let unitIndex = 0;
    while (value >= 1024 && unitIndex < units.length - 1) {
      value /= 1024;
      unitIndex += 1;
    }
    return `${value.toFixed(1)} ${units[unitIndex]}`;
  }

  return { formatDateTime, formatDate, formatDuration, formatFileSize };
}
