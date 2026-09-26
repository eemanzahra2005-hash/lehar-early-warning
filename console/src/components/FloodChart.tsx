"use client";

import type { FloodChartPoint } from "@/lib/flood";
import { Area, CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

interface FloodChartProps {
  points: FloodChartPoint[];
  observedLabel: string;
  forecastLabel: string;
  /** Label for the shaded forecast period (only drawn when there are forecast days). */
  forecastPeriodLabel: string;
  baselineLabel: string;
  baseline?: number | null;
  unit: string;
}

const OBSERVED = "#5eead4";
const FORECAST = "#c39bf5";
const AXIS = "#94a0b2";

/**
 * Observed discharge as a solid line over a soft area, the DL forecast as a
 * dashed line, and the forecast DAYS shaded. The shading marks when the
 * numbers stop being measurements; it is not an uncertainty band (the API
 * returns none, and the console never invents one). Solid vs dashed keeps
 * "measured" and "predicted" apart without relying on colour.
 */
export function FloodChart({ points, observedLabel, forecastLabel, forecastPeriodLabel, baselineLabel, baseline, unit }: FloodChartProps) {
  // Forecast-only points (no observation) define the shaded period.
  const forecastDays = points.filter((p) => p.observed === undefined && p.forecast !== undefined);
  const shadeFrom = forecastDays.length > 0 ? forecastDays[0].date : null;
  const shadeTo = forecastDays.length > 0 ? forecastDays[forecastDays.length - 1].date : null;

  return (
    <div className="space-y-2" dir="ltr">
      <div className="h-60 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={points} margin={{ top: 12, right: 12, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="obs-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={OBSERVED} stopOpacity={0.35} />
                <stop offset="100%" stopColor={OBSERVED} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
            {shadeFrom && shadeTo && (
              <ReferenceArea
                x1={shadeFrom}
                x2={shadeTo}
                fill={FORECAST}
                fillOpacity={0.08}
                stroke={FORECAST}
                strokeOpacity={0.25}
                strokeDasharray="3 3"
                label={{ value: forecastPeriodLabel, position: "insideTop", fill: FORECAST, fontSize: 11 }}
              />
            )}
            <XAxis dataKey="date" tick={{ fontSize: 11, fill: AXIS }} tickFormatter={(d: string) => d.slice(5)} stroke="rgba(255,255,255,0.15)" />
            <YAxis tick={{ fontSize: 11, fill: AXIS }} width={48} stroke="rgba(255,255,255,0.15)" />
            <Tooltip
              formatter={(value, name) => [`${Number(value).toFixed(1)} ${unit}`, name]}
              contentStyle={{
                background: "rgba(14,21,36,0.95)",
                border: "1px solid rgba(255,255,255,0.12)",
                borderRadius: 12,
                color: "#e6eaf2",
                fontSize: 12,
              }}
              labelStyle={{ color: "#fff", fontWeight: 600 }}
              cursor={{ stroke: "rgba(255,255,255,0.25)" }}
            />
            {baseline !== undefined && baseline !== null && (
              <ReferenceLine
                y={baseline}
                stroke={AXIS}
                strokeDasharray="2 4"
                label={{ value: baselineLabel, fontSize: 10, fill: AXIS, position: "insideBottomRight" }}
              />
            )}
            <Area
              type="monotone"
              dataKey="observed"
              name={observedLabel}
              stroke={OBSERVED}
              strokeWidth={2.5}
              fill="url(#obs-fill)"
              dot={{ r: 3, fill: OBSERVED, strokeWidth: 0 }}
              activeDot={{ r: 5 }}
              connectNulls={false}
            />
            <Line
              type="monotone"
              dataKey="forecast"
              name={forecastLabel}
              stroke={FORECAST}
              strokeWidth={2.5}
              strokeDasharray="6 4"
              dot={{ r: 4, strokeWidth: 2, fill: "#0e1524" }}
              connectNulls={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      {/* Legend as text + line samples: solid vs dashed, not colour alone. */}
      <ul className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted">
        <li className="flex items-center gap-2">
          <svg width="22" height="6" aria-hidden="true">
            <line x1="0" y1="3" x2="22" y2="3" stroke={OBSERVED} strokeWidth="2.5" />
          </svg>
          {observedLabel}
        </li>
        {forecastDays.length > 0 && (
          <li className="flex items-center gap-2">
            <svg width="22" height="6" aria-hidden="true">
              <line x1="0" y1="3" x2="22" y2="3" stroke={FORECAST} strokeWidth="2.5" strokeDasharray="6 4" />
            </svg>
            {forecastLabel}
          </li>
        )}
      </ul>
    </div>
  );
}
