"use client";

import { useCallback, useSyncExternalStore } from "react";

/**
 * True while a CSS media query matches. Used where CSS alone is not enough,
 * e.g. the map's district panel, which must mount in ONE place (overlay on
 * desktop, below the map on phones) so its API calls run once.
 * The server render assumes `false` (phone first).
 */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const list = window.matchMedia(query);
      list.addEventListener("change", onChange);
      return () => list.removeEventListener("change", onChange);
    },
    [query],
  );
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(query).matches,
    () => false,
  );
}
