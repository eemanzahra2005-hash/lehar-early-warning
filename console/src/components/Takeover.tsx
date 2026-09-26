"use client";

import { m } from "framer-motion";
import { Volume2, VolumeX } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useI18n } from "@/i18n/LanguageProvider";
import type { ActiveAlertSummary } from "@/lib/types";
import { levelScope, useLevelLabel } from "./Level";
import { LevelBackdrop, PulsingIcon } from "./LevelBand";
import { useLevels } from "./LevelsProvider";

/*
 * Why "acknowledge" is local here: POST /alerts/{id}/ack is a GLOBAL state
 * change (it removes the alert from /alerts/active and the banner for every
 * visitor). A member of the public dismissing their own screen must not
 * clear the warning for everyone else, so the console remembers the
 * acknowledgement per device in localStorage instead.
 */
const ACK_KEY = "lehar.console.ackedAlerts";

export function readLocalAcks(): number[] {
  try {
    const raw = window.localStorage.getItem(ACK_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((n) => typeof n === "number") : [];
  } catch {
    return [];
  }
}

function writeLocalAck(id: number) {
  try {
    // Keep only the last 200 ids so storage cannot grow without bound.
    const next = [...readLocalAcks().filter((n) => n !== id), id].slice(-200);
    window.localStorage.setItem(ACK_KEY, JSON.stringify(next));
  } catch {
    /* storage blocked: the takeover simply shows again next visit */
  }
}

/** A short two-tone alarm with the Web Audio API — no audio file to ship. */
function useAlarm(enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;
    const AudioCtx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const beep = () => {
      [880, 660].forEach((freq, i) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.frequency.value = freq;
        gain.gain.value = 0.15;
        osc.connect(gain).connect(ctx.destination);
        const start = ctx.currentTime + i * 0.35;
        osc.start(start);
        osc.stop(start + 0.3);
      });
    };
    beep();
    const id = window.setInterval(beep, 2000);
    return () => {
      window.clearInterval(id);
      void ctx.close();
    };
  }, [enabled]);
}

interface TakeoverProps {
  /** Active district rows at a takeover level, most urgent first, not yet acked on this device. */
  alerts: ActiveAlertSummary[];
  onAcknowledge: (alertId: number) => void;
}

export function Takeover({ alerts, onAcknowledge }: TakeoverProps) {
  const { t, pick, lang } = useI18n();
  const { levels } = useLevels();
  const [sound, setSound] = useState(false); // OFF by default, always
  const ackButton = useRef<HTMLButtonElement>(null);
  const current = alerts[0];
  const label = useLevelLabel(current?.level ?? 4);

  useAlarm(sound && !!current);

  useEffect(() => {
    if (current) ackButton.current?.focus();
  }, [current]);

  // The page behind must not scroll while the takeover is up.
  useEffect(() => {
    if (!current) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [current]);

  if (!current || current.alert_id === null) return null;
  const meta = levels[current.level];
  const actions = meta ? (lang === "ur" ? meta.actions_ur : meta.actions_en) : [];
  const alertId = current.alert_id;

  const acknowledge = () => {
    writeLocalAck(alertId);
    setSound(false);
    onAcknowledge(alertId);
  };

  return (
    <m.div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="takeover-title"
      aria-describedby="takeover-body"
      className={`band ${levelScope(current.level)} fixed inset-0 z-[3000] overflow-y-auto`}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2 }}
    >
      <LevelBackdrop level={current.level} />
      <m.div
        className="mx-auto flex min-h-full max-w-2xl flex-col gap-6 px-5 py-8 sm:py-12"
        initial={{ opacity: 0, y: 40, scale: 0.94 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ type: "spring", stiffness: 260, damping: 22, delay: 0.05 }}
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="inline-flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.16em] rtl:tracking-normal">
            <span className="live-dot" aria-hidden="true" />
            {t("takeover.label")}
          </p>
          <button
            type="button"
            onClick={() => setSound((s) => !s)}
            aria-pressed={sound}
            className="inline-flex min-h-11 items-center gap-2 rounded-full border border-current bg-black/20 px-4 py-2 text-sm font-semibold backdrop-blur"
          >
            {sound ? <Volume2 className="h-4 w-4" aria-hidden="true" /> : <VolumeX className="h-4 w-4" aria-hidden="true" />}
            {t("takeover.sound")}: {sound ? t("takeover.soundOn") : t("takeover.soundOff")}
          </button>
        </div>

        <div className="flex items-center gap-6">
          <span className="hero-numeral" aria-hidden="true">
            {current.level}
          </span>
          <PulsingIcon level={current.level} className="h-16 w-16 sm:h-20 sm:w-20" ringClass="p-4" />
        </div>

        <div id="takeover-title" aria-live="assertive">
          <p className="font-display text-3xl font-semibold sm:text-4xl">{label}</p>
          <p className="mt-1 text-2xl font-semibold">{current.district}</p>
        </div>

        <div id="takeover-body" className="space-y-5">
          <p className="text-xl font-medium">{pick(current.title_en, current.title_ur)}</p>
          {actions.length > 0 && (
            <div className="rounded-2xl border border-white/25 bg-black/25 p-5 backdrop-blur-sm">
              <h2 className="mb-3 text-lg font-semibold">{t("board.whatToDo")}</h2>
              <ol className="space-y-3 text-lg">
                {actions.map((action, i) => (
                  <li key={action} className="flex gap-3">
                    <span className="num grid h-7 w-7 shrink-0 place-items-center rounded-full border border-current text-sm font-semibold">
                      {i + 1}
                    </span>
                    <span>{action}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}
          {alerts.length > 1 && <p className="font-semibold">{t("takeover.moreAlerts", { n: alerts.length - 1 })}</p>}
        </div>

        <div className="mt-auto space-y-3 pt-4">
          <button
            ref={ackButton}
            type="button"
            onClick={acknowledge}
            className="lift w-full rounded-2xl bg-white px-5 py-4 text-lg font-bold text-slate-900 shadow-[0_12px_40px_-8px_rgb(0_0_0/0.6)] ring-2 ring-black/80"
          >
            {t("takeover.acknowledge")}
          </button>
          <p className="text-sm font-medium">{t("takeover.ackNote")}</p>
          <p className="text-sm font-semibold">{t("disclaimer")}</p>
        </div>
      </m.div>
    </m.div>
  );
}
