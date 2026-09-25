/**
 * Ephemeral (in-memory, not persisted) cache of the most recent full
 * POST /api/v1/predict response. GET /api/v1/history only stores
 * risk_score/risk_band per row (see backend/app/db.py) — not the full SHAP
 * explanation or confidence interval, which are comparatively large and
 * only ever needed right after the prediction that produced them. The
 * Dashboard's "latest recommendation" card reads from history, so it uses
 * this cache to show the real explanation/confidence for that exact
 * prediction when the user just ran it (matched by district + crop_type +
 * recommendation_mm + recency — see dashboard.js), and falls back to
 * "explanation unavailable" rather than showing anything invented when it
 * doesn't match (e.g. a fresh page load, or a different device/session).
 */

const MATCH_WINDOW_MS = 30 * 60 * 1000; // 30 minutes

let lastResult = null;

export function setLastPrediction(result) {
  lastResult = { ...result, at: Date.now() };
}

/** Returns the cached full prediction if it plausibly matches this history
 * row (same district/crop/recommendation, within the recency window) —
 * otherwise null. Never guesses across a mismatch. */
export function getLastPredictionFor(historyRow) {
  if (!lastResult || !historyRow) return null;
  if (Date.now() - lastResult.at > MATCH_WINDOW_MS) return null;
  const sameDistrict = lastResult.inputs_used?.district === historyRow.district;
  const sameCrop = lastResult.inputs_used?.crop_type === historyRow.crop_type;
  const sameValue = lastResult.irrigation_recommendation_mm === historyRow.recommendation_mm;
  return sameDistrict && sameCrop && sameValue ? lastResult : null;
}
