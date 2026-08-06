import { ref } from "vue";
import { useRouter } from "vue-router";

import type { Ref } from "vue";
import type { Router } from "vue-router";

type RouteSnapshot = Router["currentRoute"]["value"];

interface UseBackNavigation {
  previousRoute: Ref<RouteSnapshot | null>;
  goBack: () => void;
}

// Exported directly (not just via useBackNavigation()'s return value) so
// call sites that only need to read/reset it - e.g. a test's beforeEach -
// don't have to invoke useRouter() (and its own inject()) outside a
// component's setup().
export const previousRoute: Ref<RouteSnapshot | null> = ref(null);

/** Registered once, in router/index.ts alongside the auth guard. Ignores the
 * app's very first navigation (from has no matched route yet) and
 * navigations that only change the current route's query (e.g. switching
 * tabs within Settings) - only a genuine change of page counts as
 * "somewhere to go back to". */
export function recordPreviousRoute(to: RouteSnapshot, from: RouteSnapshot): void {
  if (from.matched.length > 0 && from.name !== to.name) {
    previousRoute.value = from;
  }
}

export function useBackNavigation(): UseBackNavigation {
  const router = useRouter();

  /** Only meaningful once previousRoute is set - callers gate showing any
   * "back" affordance on that already (see TopBar's showBack), so there's
   * no separate fallback destination to fall back to here. */
  function goBack(): void {
    if (previousRoute.value) {
      void router.push(previousRoute.value);
    }
  }

  return { previousRoute, goBack };
}
