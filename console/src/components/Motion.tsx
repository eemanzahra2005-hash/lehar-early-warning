"use client";

/*
 * Motion primitives for the whole console.
 *
 * Why these wrappers: every animation goes through framer-motion's small
 * `m` components inside <LazyMotion strict>, so the animation engine is
 * loaded once, after first paint, and a stray full-size `motion.div` is a
 * runtime error rather than a silent +30 KB. <MotionConfig reducedMotion=
 * "user"> makes every one of them honour the OS "reduce motion" setting
 * (movement is dropped; opacity fades stay, which is gentle and harmless).
 */

import { LazyMotion, MotionConfig, m, useInView } from "framer-motion";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useI18n } from "@/i18n/LanguageProvider";
import { useMediaQuery } from "@/lib/useMediaQuery";

const loadFeatures = () => import("./motion-features").then((mod) => mod.default);

export const EASE_OUT = [0.22, 1, 0.36, 1] as const;
export const SPRING = { type: "spring", stiffness: 380, damping: 32 } as const;

/*
 * The language fade and the number counters use the browser's own Web
 * Animations API / requestAnimationFrame instead of framer-motion's
 * `animate()`: importing that pulls the whole animation engine into every
 * route's first bundle, which <LazyMotion> exists to avoid.
 */
export function usePrefersReducedMotion(): boolean {
  return useMediaQuery("(prefers-reduced-motion: reduce)");
}

export function MotionProvider({ children }: { children: React.ReactNode }) {
  return (
    <LazyMotion features={loadFeatures} strict>
      <MotionConfig reducedMotion="user" transition={{ duration: 0.25, ease: EASE_OUT }}>
        {children}
      </MotionConfig>
    </LazyMotion>
  );
}

/**
 * 250 ms fade + rise when the route changes (enter only: the App Router
 * swaps pages synchronously, so an exit animation would replay the NEW page).
 * The EN <-> UR switch mirrors the whole layout to RTL; it gets a soft fade
 * in place rather than a remount, so forms keep what the user typed.
 */
export function PageTransition({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { lang } = useI18n();
  const scope = useRef<HTMLDivElement>(null);
  const firstLang = useRef(lang);
  const reduce = usePrefersReducedMotion();
  const [firstPath] = useState(pathname);
  const hasNavigated = firstPath !== pathname;

  useEffect(() => {
    if (firstLang.current === lang || !scope.current) return;
    firstLang.current = lang;
    const from = reduce ? { opacity: 0.2 } : { opacity: 0.2, transform: "translateY(6px)" };
    const to = reduce ? { opacity: 1 } : { opacity: 1, transform: "none" };
    scope.current.animate([from, to], { duration: 300, easing: "cubic-bezier(0.22, 1, 0.36, 1)" });
  }, [lang, reduce]);

  return (
    <div ref={scope}>
      {/* The first page load paints immediately (no opacity:0 in the server
          HTML, which would hold back Largest Contentful Paint until
          hydration); only later client-side navigations fade in. */}
      <m.div
        key={pathname}
        initial={hasNavigated ? { opacity: 0, y: 8 } : false}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.25, ease: EASE_OUT }}
      >
        {children}
      </m.div>
    </div>
  );
}

const listVariants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.04 } },
};
const itemVariants = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0, transition: { duration: 0.3, ease: EASE_OUT } },
};

/** A list whose children reveal one after another (40 ms apart). */
export function StaggerList({
  children,
  className,
  as = "ul",
  ...rest
}: { children: React.ReactNode; className?: string; as?: "ul" | "ol" | "div" } & React.AriaAttributes) {
  const Tag = as === "ol" ? m.ol : as === "div" ? m.div : m.ul;
  return (
    <Tag className={className} variants={listVariants} initial="hidden" animate="show" {...rest}>
      {children}
    </Tag>
  );
}

export function StaggerItem({
  children,
  className,
  as = "li",
  style,
}: {
  children: React.ReactNode;
  className?: string;
  as?: "li" | "div";
  style?: React.CSSProperties;
}) {
  const Tag = as === "div" ? m.div : m.li;
  return (
    <Tag className={className} variants={itemVariants} style={style}>
      {children}
    </Tag>
  );
}

/**
 * A number that counts up to its value when it scrolls into view (and
 * between values on refresh). The digits are written straight into the DOM
 * each frame rather than through React state, so a row of counters costs no
 * re-renders. Screen readers get the final value only.
 */
export function CountUp({ value, decimals = 0, className }: { value: number; decimals?: number; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const digits = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true });
  const reduce = usePrefersReducedMotion();
  const from = useRef(0);

  useEffect(() => {
    const el = digits.current;
    if (!inView || !el) return;
    const start = from.current;
    from.current = value;
    if (reduce || start === value) {
      el.textContent = value.toFixed(decimals); // reduced motion: jump straight to the value
      return;
    }
    // 900 ms ease-out (cubic), one frame at a time.
    const began = performance.now();
    let frame = requestAnimationFrame(function tick(now) {
      const t = Math.min(1, (now - began) / 900);
      el.textContent = (start + (value - start) * (1 - (1 - t) ** 3)).toFixed(decimals);
      if (t < 1) frame = requestAnimationFrame(tick);
    });
    return () => cancelAnimationFrame(frame);
  }, [inView, value, reduce, decimals]);

  return (
    <span ref={ref} className={className}>
      <span ref={digits} aria-hidden="true">
        {(0).toFixed(decimals)}
      </span>
      <span className="sr-only">{value.toFixed(decimals)}</span>
    </span>
  );
}
