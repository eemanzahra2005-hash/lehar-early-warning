/**
 * Client-side mirror of the Farm Risk Score's 5 raw components (see
 * backend/app/services/risk.py's compute_components / docs/RISK_SCORE.md).
 * These 5 divisors are fixed constants — NOT environment-configurable —
 * so recomputing them here from a history row's own persisted inputs
 * (soil moisture, weather, canal flow) is an exact, honest reproduction of
 * the documented formula, not a guess. Used only to render a component
 * breakdown for rows where the full breakdown wasn't persisted (history
 * only stores risk_score/risk_band — see app/db.py); the score/band shown
 * alongside it always comes from that real persisted value, never
 * recomputed here, since the composite weights ARE env-configurable
 * server-side and only the server's own computation is authoritative for
 * the final number.
 */
export function computeRiskComponents({
  soil_moisture_pct,
  evapotranspiration_mm,
  temperature_c,
  canal_flow_cusecs,
  rainfall_mm,
}) {
  const clamp01 = (v) => Math.max(0, Math.min(1, v));
  return {
    moisture_deficit: clamp01((35 - soil_moisture_pct) / 25),
    et0_demand: clamp01((evapotranspiration_mm - 5) / 5),
    heat_stress: clamp01((temperature_c - 35) / 10),
    water_scarcity: clamp01((300 - canal_flow_cusecs) / 300),
    rain_relief: clamp01(rainfall_mm / 20),
  };
}
