"use client";

import { Bell, ChartColumn, Languages, ListFilter, Lock, Map as MapIcon, Siren, Sprout } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useI18n } from "@/i18n/LanguageProvider";
import type { DictKey } from "@/i18n/dictionary";

const NAV: { href: string; key: DictKey; icon: typeof Bell }[] = [
  { href: "/", key: "nav.board", icon: Siren },
  { href: "/map", key: "nav.map", icon: MapIcon },
  { href: "/alerts", key: "nav.feed", icon: ListFilter },
  { href: "/subscribe", key: "nav.subscribe", icon: Bell },
  { href: "/predict", key: "nav.predict", icon: Sprout },
  { href: "/explain", key: "nav.explain", icon: ChartColumn },
  { href: "/admin", key: "nav.admin", icon: Lock },
];

export function Header() {
  const { t, lang, setLang } = useI18n();
  const pathname = usePathname();
  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

  return (
    <header className="sticky top-0 z-[1000] border-b border-slate-200 bg-white/95 backdrop-blur">
      <div className="mx-auto flex max-w-5xl items-center justify-between gap-3 px-4 py-2">
        <Link href="/" className="flex items-baseline gap-2 font-bold text-slate-900">
          <span className="text-xl tracking-tight">{t("app.name")}</span>
          <span className="hidden text-sm font-medium text-slate-600 sm:inline">{t("app.tagline")}</span>
        </Link>
        <button
          type="button"
          onClick={() => setLang(lang === "en" ? "ur" : "en")}
          aria-label={t("lang.toggleLabel")}
          className="btn-secondary"
        >
          <Languages className="h-4 w-4" aria-hidden="true" />
          <span lang={lang === "en" ? "ur" : "en"}>{t("lang.toggle")}</span>
        </button>
      </div>
      {/* Horizontal scroll on phones rather than a hamburger: every
          destination stays one tap away during an emergency. */}
      <nav aria-label="Main" className="mx-auto max-w-5xl overflow-x-auto px-2">
        <ul className="flex gap-1 pb-1">
          {NAV.map(({ href, key, icon: Icon }) => (
            <li key={href}>
              <Link
                href={href}
                aria-current={isActive(href) ? "page" : undefined}
                className={`flex items-center gap-1.5 whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium ${
                  isActive(href) ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-slate-100"
                }`}
              >
                <Icon className="h-4 w-4" aria-hidden="true" />
                {t(key)}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </header>
  );
}

/**
 * The disclaimer is shown in BOTH languages on every page, whatever the
 * selected language (CLAUDE.md rule 12).
 */
export function Footer() {
  const { t } = useI18n();
  return (
    <footer className="mt-12 border-t border-slate-200 bg-slate-50">
      <div className="mx-auto max-w-5xl space-y-1 px-4 py-6 text-sm text-slate-700">
        <p lang="en" dir="ltr" className="font-semibold">
          Research advisory — NDMA/PMD/PDMA official warnings are authoritative.
        </p>
        <p lang="ur" dir="rtl" className="font-semibold urdu">
          تحقیقی مشورہ — این ڈی ایم اے/پی ایم ڈی/پی ڈی ایم اے کی سرکاری وارننگ ہی مستند ہے۔
        </p>
        <p className="pt-2 text-slate-600">{t("footer.research")}</p>
      </div>
    </footer>
  );
}
