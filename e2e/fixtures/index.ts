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
