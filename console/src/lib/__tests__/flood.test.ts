import { describe, expect, it } from "vitest";
import { forecastPoints, observedPointsFromDetail } from "../flood";
import type { FloodDistrictDetail, FloodForecastResponse } from "../types";

const days = (n: number, from = 1) => Array.from({ length: n }, (_, i) => `2026-09-${String(from + i).padStart(2, "0")}`);

describe("flood chart series", () => {
  it("keeps the last 7 observed days and joins the D+1..D+3 forecast to them", () => {
    const forecast = {
      observed: { unit: "m³/s", dates: days(14), values: days(14).map((_, i) => i), baseline_median: 5 },
      predicted: { unit: "m³/s", dates: days(3, 15), values: [20, 21, 22], peak: 22, anomaly_ratio: 4 },
    } as unknown as FloodForecastResponse;
    const points = forecastPoints(forecast);
    expect(points).toHaveLength(10);
    expect(points[0]).toEqual({ date: "2026-09-08", observed: 7 });
    expect(points[6]).toEqual({ date: "2026-09-14", observed: 13, forecast: 13 });
    expect(points.slice(7).map((p) => p.forecast)).toEqual([20, 21, 22]);
    expect(points.slice(7).every((p) => p.observed === undefined)).toBe(true);
  });

  it("never labels GloFAS forecast days as observed in the fallback", () => {
    const detail = {
      discharge: { unit: "m³/s", dates: days(20), values: days(20).map((_, i) => i), baseline_median: 1, forecast_max: 1, anomaly_ratio: 1 },
    } as unknown as FloodDistrictDetail;
    const points = observedPointsFromDetail(detail, "2026-09-10");
    expect(points.map((p) => p.date)).toEqual(days(7, 4));
    expect(observedPointsFromDetail({ discharge: null } as FloodDistrictDetail, "2026-09-10")).toEqual([]);
  });
});
