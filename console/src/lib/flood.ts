import type { FloodDistrictDetail, FloodForecastResponse } from "./types";

export const OBSERVED_DAYS = 7;

export interface FloodChartPoint {
  date: string;
  observed?: number;
  forecast?: number;
}

/**
 * Last 7 observed days + the model's D+1..D+3. The forecast line starts at
 * the last observed point so the two lines join visually, which mirrors how
 * the backend prepends today's observation for its own rising test.
 */
export function forecastPoints(forecast: FloodForecastResponse): FloodChartPoint[] {
  const { dates, values } = forecast.observed;
  const start = Math.max(0, dates.length - OBSERVED_DAYS);
  const points: FloodChartPoint[] = dates.slice(start).map((date, i) => ({ date, observed: values[start + i] }));
  if (points.length > 0) points[points.length - 1].forecast = points[points.length - 1].observed;
  forecast.predicted.dates.forEach((date, i) => points.push({ date, forecast: forecast.predicted.values[i] }));
  return points;
}

/**
 * Fallback when the DL forecast is unavailable (503): Flood Watch's GloFAS
 * series mixes past days and GloFAS's own forecast days, so keep only dates
 * up to today — "observed" must mean observed.
 */
export function observedPointsFromDetail(detail: FloodDistrictDetail, today: string): FloodChartPoint[] {
  const series = detail.discharge;
  if (!series) return [];
  const past = series.dates.map((date, i) => ({ date, observed: series.values[i] })).filter((p) => p.date <= today);
  return past.slice(-OBSERVED_DAYS);
}
