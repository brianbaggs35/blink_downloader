/**
 * Fixture data the e2e stack is seeded with.
 *
 * Seeding happens in the backend container at boot
 * (backend/app/testing/seed.py) and is idempotent. Override the values with
 * BLINK_E2E_ADMIN_EMAIL / BLINK_E2E_ADMIN_PASSWORD on the backend service and
 * mirror them here via environment if you change them.
 */
export const seededAdmin = {
  email: process.env.BLINK_E2E_ADMIN_EMAIL ?? "e2e-admin@example.com",
  password: process.env.BLINK_E2E_ADMIN_PASSWORD ?? "e2e-admin-password-123",
  displayName: "E2E Admin",
};

// Mirrors backend/app/testing/seed.py - keep in sync if the seed changes.
export const seededCameras = {
  frontDoor: "Front Door",
  backyard: "Backyard",
} as const;

export const seededPerson = {
  name: "Alex Demo",
};

export const seededAnalyses = {
  routine: {
    summary: "A package is dropped off at the front door; nothing unusual.",
  },
  suspicious: {
    summary: "A person lingers by the front door for an extended period after dark.",
  },
};
