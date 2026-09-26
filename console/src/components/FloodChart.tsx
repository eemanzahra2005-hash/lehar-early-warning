"use client";

import type { FloodChartPoint } from "@/lib/flood";
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";


interface FloodChartProps {
  points: FloodChartPoint[];
  observedLabel: string;
  forecastLabel: string;
  baseline?: number | null;
  unit: string;
}

/**
 * Observed discharge as a solid line and the DL forecast as a dashed line,
 * so "measured" and "predicted" are distinguishable without colour.
 */
export function FloodChart({ points, observedLabel, forecastLabel, baseline, unit }: FloodChartProps) {
  return (
    <div className="h-56 w-full" dir="ltr">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
          <CartesianGrid stroke="#e2e8f0" />
          <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(d: string) => d.slice(5)} />
          <YAxis tick={{ fontSize: 11 }} width={48} />
          <Tooltip formatter={(value) => `${Number(value).toFixed(1)} ${unit}`} />
          <Legend />
          {baseline !== undefined && baseline !== null && (
            <ReferenceLine y={baseline} stroke="#64748b" strokeDasharray="2 4" label={{ value: "baseline", fontSize: 10 }} />
          )}
          <Line type="monotone" dataKey="observed" name={observedLabel} stroke="#1d4ed8" strokeWidth={2} dot={{ r: 3 }} connectNulls={false} />
          <Line
            type="monotone"
            dataKey="forecast"
            name={forecastLabel}
            stroke="#7b2fbf"
            strokeWidth={2}
            strokeDasharray="6 4"
            dot={{ r: 4, strokeWidth: 2 }}
            connectNulls={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
