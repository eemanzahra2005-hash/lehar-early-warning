"use client";

import { createContext, useContext, useMemo } from "react";
import { api } from "@/lib/api";
import { indexLevels } from "@/lib/levels";
import type { AlertLevelInfo } from "@/lib/types";
import { useApi } from "@/lib/useApi";

interface LevelsContextValue {
  /** Level metadata by number, or {} until GET /alerts/levels answers. */
  levels: Record<number, AlertLevelInfo>;
  loading: boolean;
  error: unknown;
  reload: () => void;
}

const LevelsContext = createContext<LevelsContextValue>({ levels: {}, loading: true, error: null, reload: () => {} });

/**
 * Fetches the level scheme once per page load. The backend's levels.py is
 * the single source of truth for names and actions; until it answers, badges
 * still render icon + number + colour token (see lib/levels.ts).
 */
export function LevelsProvider({ children }: { children: React.ReactNode }) {
  const { data, loading, error, reload } = useApi(api.levels);
  const value = useMemo(
    () => ({ levels: data ? indexLevels(data.levels) : {}, loading, error, reload }),
    [data, loading, error, reload],
  );
  return <LevelsContext.Provider value={value}>{children}</LevelsContext.Provider>;
}

export function useLevels(): LevelsContextValue {
  return useContext(LevelsContext);
}
