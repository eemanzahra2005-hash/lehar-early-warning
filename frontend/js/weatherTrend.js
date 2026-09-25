/**
 * Real day-over-day weather deltas for the dashboard KPI tiles, with no
 * backend involvement and no invented "yesterday" numbers. Every value
 * compared here was actually fetched from the live API on a previous visit
 * and stored locally, keyed by district + calendar date — if the app wasn't
 * opened yesterday, the comparison is honestly labeled "N days ago" instead
 * of pretending it's "yesterday".
 */

// All browser storage keys share the `lehar_` prefix so they never collide
// with other apps served from the same origin.
const KEY_PREFIX = 'lehar_wx_trend_';
const MAX_ENTRIES = 14;

function todayKey() {
  return new Date().toISOString().slice(0, 10);
}

function load(district) {
  try {
    const raw = localStorage.getItem(KEY_PREFIX + district);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function save(district, entries) {
  try {
    localStorage.setItem(KEY_PREFIX + district, JSON.stringify(entries.slice(-MAX_ENTRIES)));
  } catch {
    /* localStorage unavailable (e.g. private mode quota) — trend just won't persist */
  }
}

/**
 * Records today's real fetched snapshot for `district` (upserting today's
 * entry so re-fetches within the same day don't create duplicates), and
 * returns the most recent PRIOR day's snapshot plus how many days old it is
 * — or null if there is no prior snapshot yet (first visit).
 */
export function recordAndDiff(district, snapshot) {
  const entries = load(district);
  const today = todayKey();
  const withoutToday = entries.filter((e) => e.date !== today);
  const previous = withoutToday[withoutToday.length - 1] || null;

  withoutToday.push({ date: today, ...snapshot });
  save(district, withoutToday);

  if (!previous) return null;
  const daysAgo = Math.max(1, Math.round((new Date(today) - new Date(previous.date)) / 86400000));
  return { ...previous, daysAgo };
}
