"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { type DictKey, type Lang, translate } from "./dictionary";

interface LanguageContextValue {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (key: DictKey, vars?: Record<string, string | number>) => string;
  /** Pick the EN or UR variant of a backend-supplied bilingual field. */
  pick: (en: string, ur: string) => string;
}

const LanguageContext = createContext<LanguageContextValue | null>(null);
const STORAGE_KEY = "lehar.console.lang";

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  // Server render is always English; the saved choice is applied after
  // hydration so the server and first client render agree.
  const [lang, setLangState] = useState<Lang>("en");

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time read of a browser-only preference after hydration
      if (saved === "ur" || saved === "en") setLangState(saved);
    } catch {
      /* storage blocked: stay in English */
    }
  }, []);

  useEffect(() => {
    // Urdu is right-to-left: flipping <html dir> lets the browser mirror the
    // whole layout instead of every component handling it.
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "ur" ? "rtl" : "ltr";
  }, [lang]);

  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* ignore */
    }
  }, []);

  const value = useMemo<LanguageContextValue>(
    () => ({
      lang,
      setLang,
      t: (key, vars) => translate(lang, key, vars),
      pick: (enText, urText) => (lang === "ur" && urText ? urText : enText),
    }),
    [lang, setLang],
  );

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useI18n(): LanguageContextValue {
  const value = useContext(LanguageContext);
  if (!value) throw new Error("useI18n must be used inside <LanguageProvider>");
  return value;
}
