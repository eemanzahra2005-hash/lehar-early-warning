"use client";

import { Volume2, VolumeX } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useI18n } from "@/i18n/LanguageProvider";
import { levelToken } from "@/lib/levels";
import type { ActiveAlertSummary } from "@/lib/types";
import { LevelIcon, useLevelLabel } from "./Level";
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

  if (!current || current.alert_id === null) return null;
  const token = levelToken(current.level);
  const meta = levels[current.level];
  const actions = meta ? (lang === "ur" ? meta.actions_ur : meta.actions_en) : [];
  const alertId = current.alert_id;

  const acknowledge = () => {
    writeLocalAck(alertId);
    setSound(false);
    onAcknowledge(alertId);
  };

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="takeover-title"
      aria-describedby="takeover-body"
      className={`${token.className} takeover-flash fixed inset-0 z-[3000] overflow-y-auto`}
    >
      <div className="mx-auto flex min-h-full max-w-2xl flex-col gap-5 px-5 py-8">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm font-semibold uppercase tracking-wider">{t("takeover.label")}</p>
          <button
            type="button"
            onClick={() => setSound((s) => !s)}
            aria-pressed={sound}
            className="inline-flex items-center gap-2 rounded-md border border-current px-3 py-1.5 text-sm font-medium"
          >
            {sound ? <Volume2 className="h-4 w-4" aria-hidden="true" /> : <VolumeX className="h-4 w-4" aria-hidden="true" />}
            {t("takeover.sound")}: {sound ? t("takeover.soundOn") : t("takeover.soundOff")}
          </button>
        </div>

        <div className="flex items-center gap-4">
          <span className="text-[7rem] font-black leading-none" aria-hidden="true">
            {current.level}
          </span>
          <LevelIcon level={current.level} className="h-20 w-20" />
        </div>

        <div id="takeover-title" aria-live="assertive">
          <p className="text-3xl font-bold">{label}</p>
          <p className="mt-1 text-2xl font-semibold">{current.district}</p>
        </div>

        <div id="takeover-body" className="space-y-4">
          <p className="text-xl">{pick(current.title_en, current.title_ur)}</p>
          {actions.length > 0 && (
            <div>
              <h2 className="mb-2 text-lg font-bold">{t("board.whatToDo")}</h2>
              <ol className="list-decimal space-y-2 ps-6 text-lg">
                {actions.map((action) => (
                  <li key={action}>{action}</li>
                ))}
              </ol>
            </div>
          )}
          {alerts.length > 1 && <p className="font-medium">{t("takeover.moreAlerts", { n: alerts.length - 1 })}</p>}
        </div>

        <div className="mt-auto space-y-3 pt-4">
          <button
            ref={ackButton}
            type="button"
            onClick={acknowledge}
            className="w-full rounded-lg bg-white px-5 py-4 text-lg font-bold text-slate-900 ring-2 ring-black"
          >
            {t("takeover.acknowledge")}
          </button>
          <p className="text-sm">{t("takeover.ackNote")}</p>
          <p className="text-sm font-semibold">{t("disclaimer")}</p>
        </div>
      </div>
    </div>
  );
}
