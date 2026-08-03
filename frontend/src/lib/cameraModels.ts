/**
 * Blink's API only ever reports a camera's internal product codename (e.g.
 * "catalina") - there is no separate model-number/marketing-name field
 * anywhere in Blink's API surface (verified directly against blinkpy's own
 * source, which only ever reads/branches on this same raw string). This
 * table translates the codenames we've been able to confirm into their real
 * product names; anything else falls back to the raw codename unchanged
 * rather than guessing, since a wrong hardware name would be worse than an
 * unfamiliar one.
 *
 * Confirmed sources: "catalina" and "sonoran" from the household's own
 * hardware; "superior" from blinkpy's own test docstring ("wired floodlight
 * (superior) camera support"); "owl" from blinkpy's `/owls/...` API routing,
 * which is used specifically for `BlinkCameraMini`; "doorbell"/"lotus" from
 * blinkpy's own dispatch bucket and `homescreen["doorbells"]` handling.
 */
const CAMERA_MODEL_NAMES: Record<string, string> = {
  catalina: "Blink Outdoor Gen 3",
  sonoran: "Blink Outdoor 4 (2K+)",
  superior: "Blink Floodlight Camera",
  owl: "Blink Mini",
  doorbell: "Blink Video Doorbell",
  lotus: "Blink Video Doorbell",
};

export function cameraModelLabel(cameraType: string): string {
  return CAMERA_MODEL_NAMES[cameraType.toLowerCase()] ?? cameraType;
}
