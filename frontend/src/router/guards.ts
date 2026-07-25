import { useAuthStore } from "@/stores/auth";

import type { RouteLocationNormalizedGeneric } from "vue-router";

type GuardResult = boolean | { name: string; query?: Record<string, string> };

/** First run goes to /setup; anonymous users to /login; the rest through. */
export async function authGuard(to: RouteLocationNormalizedGeneric): Promise<GuardResult> {
  const auth = useAuthStore();
  await auth.bootstrap();

  if (!auth.initialized) {
    return to.name === "setup" ? true : { name: "setup" };
  }
  if (to.name === "setup") {
    return auth.isAuthenticated ? { name: "library" } : { name: "login" };
  }
  if (to.name === "login") {
    return auth.isAuthenticated ? { name: "library" } : true;
  }
  if (auth.isAuthenticated) {
    return true;
  }
  return { name: "login", query: { redirect: to.fullPath } };
}
