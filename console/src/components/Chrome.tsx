"use client";

import { m } from "framer-motion";
import { Bell, ChartColumn, Ellipsis, ListFilter, Lock, Map as MapIcon, Siren, Sprout } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useI18n } from "@/i18n/LanguageProvider";
import type { DictKey } from "@/i18n/dictionary";
import { SPRING } from "./Motion";

type NavItem = { href: string; key: DictKey; icon: typeof Bell };

const NAV: NavItem[] = [
  { href: "/", key: "nav.board", icon: Siren },
  { href: "/map", key: "nav.map", icon: MapIcon },
  { href: "/alerts", key: "nav.feed", icon: ListFilter },
  { href: "/subscribe", key: "nav.subscribe", icon: Bell },
  { href: "/predict", key: "nav.predict", icon: Sprout },
  { href: "/explain", key: "nav.explain", icon: ChartColumn },
  { href: "/admin", key: "nav.admin", icon: Lock },
];
// Phones get the four emergency destinations as tabs; the rest sit under "More".
const TABS = NAV.slice(0, 4);
const MORE = NAV.slice(4);

function useIsActive() {
  const pathname = usePathname();
  return (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));
}

/** The LEHAR mark: a wave ("lehar" is Urdu for wave) over a rising level line. */
export function WaveMark({ className = "h-7 w-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true" fill="none">
      <defs>
        <linearGradient id="lehar-wave" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
          <stop stopColor="#5EEAD4" />
          <stop offset="1" stopColor="#38BDF8" />
        </linearGradient>
      </defs>
      <rect x="1" y="1" width="30" height="30" rx="9" stroke="url(#lehar-wave)" strokeOpacity="0.45" />
      <path d="M5 18c3 0 3-4 6-4s3 4 6 4 3-4 6-4 3 4 4 4" stroke="url(#lehar-wave)" strokeWidth="2.4" strokeLinecap="round" />
      <path d="M5 24c3 0 3-3 6-3s3 3 6 3 3-3 6-3 3 3 4 3" stroke="url(#lehar-wave)" strokeOpacity="0.5" strokeWidth="2" strokeLinecap="round" />
      <circle cx="23" cy="9" r="2" fill="#5EEAD4" />
    </svg>
  );
}

/**
 * EN | اردو pill with a sliding thumb. A radio group (not a toggle button),
 * so a screen reader announces both options and which one is chosen.
 */
function LanguageSwitch() {
  const { t, lang, setLang } = useI18n();
  const options = [
    { code: "en" as const, label: "EN" },
    { code: "ur" as const, label: "اردو" },
  ];
  return (
    <div
      role="radiogroup"
      aria-label={t("common.language")}
      className="relative flex items-center rounded-full border border-line bg-white/5 p-1"
      dir="ltr"
    >
      {options.map((option) => {
        const active = lang === option.code;
        return (
          <button
            key={option.code}
            type="button"
            role="radio"
            aria-checked={active}
            lang={option.code}
            onClick={() => setLang(option.code)}
            className={`press relative z-10 min-h-11 min-w-12 rounded-full px-3 text-sm font-semibold transition-colors ${
              active ? "text-[#04201f]" : "text-muted hover:text-white"
            } ${option.code === "ur" ? "urdu leading-none" : ""}`}
          >
            {active && (
              <m.span
                layoutId="lang-thumb"
                transition={SPRING}
                className="absolute inset-0 -z-10 rounded-full bg-gradient-to-r from-[#5eead4] to-[#38bdf8]"
                aria-hidden="true"
              />
            )}
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

export function Header() {
  const { t } = useI18n();
  const isActive = useIsActive();

  return (
    <header
      className="sticky top-0 z-[1100] border-b border-line bg-[#070b14]/70 backdrop-blur-xl backdrop-saturate-150"
      style={{ height: "var(--header-h)" }}
    >
      <div className="page flex h-full items-center justify-between gap-4">
        <Link href="/" className="group flex min-h-11 shrink-0 items-center gap-2.5 rounded-lg" aria-label={`${t("app.name")} — ${t("app.tagline")}`}>
          <WaveMark className="h-8 w-8 transition-transform duration-300 group-hover:rotate-[-6deg]" />
          <span className="font-display text-lg font-bold tracking-[0.18em] text-white">LEHAR</span>
          <span className="hidden text-sm text-muted xl:inline">{t("app.tagline")}</span>
        </Link>

        <nav aria-label={t("nav.main")} className="hidden min-w-0 md:block">
          <ul className="flex items-center gap-1">
            {NAV.map(({ href, key, icon: Icon }) => {
              const active = isActive(href);
              return (
                <li key={href}>
                  <Link
                    href={href}
                    title={t(key)}
                    aria-current={active ? "page" : undefined}
                    className={`nav-link relative flex items-center gap-1.5 whitespace-nowrap rounded-lg px-2.5 py-2 text-sm font-medium transition-colors lg:px-3 ${
                      active ? "text-white" : "text-muted hover:bg-white/5 hover:text-white"
                    }`}
                  >
                    <Icon className="h-4 w-4" aria-hidden="true" />
                    {/* Tablets get icons only (7 labels do not fit); the label stays for screen readers. */}
                    <span className="sr-only lg:not-sr-only">{t(key)}</span>
                    {active && (
                      <m.span
                        layoutId="nav-underline"
                        transition={SPRING}
                        className="absolute inset-x-2 -bottom-[11px] h-0.5 rounded-full bg-accent shadow-[0_0_12px_rgb(94_234_212/0.8)]"
                        aria-hidden="true"
                      />
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        <LanguageSwitch />
      </div>
    </header>
  );
}

/** Phones: a thumb-reach bottom tab bar instead of the top nav. */
export function BottomNav() {
  const { t } = useI18n();
  const isActive = useIsActive();
  const pathname = usePathname();
  const [openFor, setOpenFor] = useState<string | null>(null);
  const moreRef = useRef<HTMLDivElement>(null);
  // The sheet belongs to the page it was opened on, so navigating closes it.
  const open = openFor === pathname;
  const moreActive = MORE.some((item) => isActive(item.href));

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpenFor(null);
    const onClick = (e: MouseEvent) => {
      if (moreRef.current && !moreRef.current.contains(e.target as Node)) setOpenFor(null);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  const tabClass = (active: boolean) =>
    // 14 px labels (the phone minimum); a long label wraps to two lines
    // rather than being cut off at 360 px.
    `press relative flex h-full w-full flex-col items-center justify-center gap-0.5 text-sm font-medium leading-[1.1] ${
      active ? "text-white" : "text-muted"
    }`;
  const indicator = (
    <m.span
      layoutId="tab-indicator"
      transition={SPRING}
      className="absolute top-0 h-0.5 w-10 rounded-full bg-accent shadow-[0_0_12px_rgb(94_234_212/0.9)]"
      aria-hidden="true"
    />
  );

  return (
    <nav
      aria-label={t("nav.mobile")}
      className="fixed inset-x-0 bottom-0 z-[1100] border-t border-line bg-[#070b14]/85 backdrop-blur-xl md:hidden"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      <ul className="grid grid-cols-5" style={{ height: "var(--tabbar-h)" }}>
        {TABS.map(({ href, key, icon: Icon }) => {
          const active = isActive(href);
          return (
            <li key={href}>
              <Link href={href} aria-current={active ? "page" : undefined} className={tabClass(active)}>
                {active && indicator}
                <Icon className="h-5 w-5" aria-hidden="true" />
                <span className="line-clamp-2 max-w-full px-0.5 text-center">{t(key)}</span>
              </Link>
            </li>
          );
        })}
        <li>
          <div ref={moreRef} className="relative h-full">
            <button
              type="button"
              aria-expanded={open}
              aria-controls="more-menu"
              onClick={() => setOpenFor(open ? null : pathname)}
              className={tabClass(moreActive || open)}
            >
              {moreActive && indicator}
              <Ellipsis className="h-5 w-5" aria-hidden="true" />
              <span>{t("nav.more")}</span>
            </button>
            {open && (
              <m.ul
                id="more-menu"
                initial={{ opacity: 0, y: 8, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                style={{ transformOrigin: "bottom" }}
                transition={SPRING}
                className="glass absolute bottom-[calc(100%+8px)] end-2 w-52 overflow-hidden bg-[#0e1524]/95 p-1.5"
              >
                {MORE.map(({ href, key, icon: Icon }) => (
                  <li key={href}>
                    <Link
                      href={href}
                      aria-current={isActive(href) ? "page" : undefined}
                      className={`flex min-h-11 items-center gap-2.5 rounded-xl px-3 text-sm font-medium ${
                        isActive(href) ? "bg-white/10 text-white" : "text-ink hover:bg-white/5"
                      }`}
                    >
                      <Icon className="h-4 w-4" aria-hidden="true" />
                      {t(key)}
                    </Link>
                  </li>
                ))}
              </m.ul>
            )}
          </div>
        </li>
      </ul>
    </nav>
  );
}

/**
 * The disclaimer strip, in BOTH languages on every page whatever the chosen
 * language (CLAUDE.md rule 12). From tablet width up it is pinned to the
 * bottom of the viewport, so it is always on screen; on phones it closes
 * every page instead, because a pinned two-line strip plus the tab bar would
 * cover a fifth of a small screen during an emergency.
 */
export function Footer() {
  const { t } = useI18n();
  return (
    <footer className="pb-tabbar z-[1050] mt-12 border-t border-line bg-[#070b14]/80 backdrop-blur-xl md:sticky md:bottom-0">
      <div className="page flex flex-col gap-y-1 py-3 text-sm md:py-1.5 md:text-xs">
        <p className="flex flex-col gap-x-6 gap-y-1 text-ink md:flex-row md:flex-wrap md:items-center md:justify-center">
          <span lang="en" dir="ltr" className="font-medium">
            <span className="me-2 inline-block h-1.5 w-1.5 -translate-y-0.5 rounded-full bg-warn align-middle" aria-hidden="true" />
            Research advisory — NDMA/PMD/PDMA official warnings are authoritative.
          </span>
          <span lang="ur" dir="rtl" className="urdu font-medium md:text-sm md:leading-[1.9]">
            تحقیقی مشورہ — این ڈی ایم اے/پی ایم ڈی/پی ڈی ایم اے کی سرکاری وارننگ ہی مستند ہے۔
          </span>
        </p>
        {/* Desktop strip stays one line: EN + UR already say "research, not official". */}
        <p className="text-xs text-muted md:hidden">{t("footer.research")}</p>
      </div>
    </footer>
  );
}
