"use client";

import { Info, OctagonAlert, ShieldAlert, Siren, TriangleAlert, Wrench, type LucideIcon } from "lucide-react";
import { useI18n } from "@/i18n/LanguageProvider";
import { levelToken, type LevelToken } from "@/lib/levels";
import { useLevels } from "./LevelsProvider";

const ICONS: Record<LevelToken["icon"], LucideIcon> = {
  Wrench,
  Info,
  TriangleAlert,
  OctagonAlert,
  Siren,
  ShieldAlert,
};

export function LevelIcon({ level, className = "h-5 w-5" }: { level: number; className?: string }) {
  const Icon = ICONS[levelToken(level).icon];
  return <Icon className={className} aria-hidden="true" />;
}

/** "Level 3 · Warning" in the current language; the name is omitted until metadata loads. */
export function useLevelLabel(level: number): string {
  const { t, pick } = useI18n();
  const { levels } = useLevels();
  const meta = levels[level];
  const number = level === 0 ? "OPS" : t("common.level", { n: level });
  return meta ? `${number} · ${pick(meta.name_en, meta.name_ur)}` : number;
}

/**
 * A level is never shown by colour alone: icon + level number + name, on the
 * level's colour token with its AA-contrast text colour.
 */
export function LevelBadge({ level, size = "md" }: { level: number; size?: "sm" | "md" | "lg" }) {
  const label = useLevelLabel(level);
  const token = levelToken(level);
  const sizes = {
    sm: "text-xs px-2 py-0.5 gap-1",
    md: "text-sm px-2.5 py-1 gap-1.5",
    lg: "text-lg px-3 py-1.5 gap-2",
  };
  const icon = { sm: "h-3.5 w-3.5", md: "h-4 w-4", lg: "h-6 w-6" };
  return (
    <span className={`${token.className} level-outline inline-flex items-center rounded-md font-semibold ${sizes[size]}`}>
      <LevelIcon level={level} className={icon[size]} />
      <span>{label}</span>
    </span>
  );
}
