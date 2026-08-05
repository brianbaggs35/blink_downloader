/**
 * Blink never reports a real battery percentage - blinkpy's own
 * `battery_level` is a coarse 0-ish signal-bar int from the cloud's
 * "signals" block, not 0-100 (verified against blinkpy's source). The only
 * meaningful, well-defined signal is this raw `battery_state` string
 * ("ok"/"low"/etc, passed through unnormalized), matched case-insensitively
 * since Blink's cloud doesn't guarantee casing.
 */
export type BatteryStatus = "ok" | "low" | "unknown";

export interface BatteryStatusMeta {
  label: string;
  severity: "success" | "danger" | "secondary";
  icon: string;
}

export const BATTERY_STATUS_META: Record<BatteryStatus, BatteryStatusMeta> = {
  ok: { label: "OK", severity: "success", icon: "mdi:battery" },
  low: { label: "Low", severity: "danger", icon: "mdi:battery-alert" },
  unknown: { label: "No data", severity: "secondary", icon: "mdi:battery-unknown" },
};

export function batteryStatus(value: string | null | undefined): BatteryStatus {
  const normalized = (value ?? "").trim().toLowerCase();
  if (normalized === "low") return "low";
  if (normalized === "ok") return "ok";
  return "unknown";
}
