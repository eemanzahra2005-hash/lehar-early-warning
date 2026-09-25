/**
 * Maps our 107 canonical district names (backend/ml/districts.py) onto the
 * "shapeName" property of frontend/assets/geo/pakistan_districts.geojson
 * (geoBoundaries PAK ADM2 2019 release, 126 units) wherever they differ from
 * a direct string match. Built by manually diffing the district names
 * against the geojson's shapeName list (see PROGRESS.md Phase 5 and
 * Phase 5.5 notes).
 *
 * Known gaps — these 6 districts have no matching polygon in this dataset at
 * all (geoBoundaries' PAK ADM2 release either doesn't include them as a
 * separate unit, predates their creation, or — for Mirpur/Kotli — only has a
 * single unified "Azad Kashmir" polygon covering the whole region). They
 * cannot be drawn on the choropleth until a more complete boundary source is
 * vendored; mapView.js logs each one (and any future mismatch) to the
 * console on load instead of silently hiding it:
 *   - "Larkana" (Sindh)
 *   - "Chiniot" (Punjab) — a 2009-created district, newer than this
 *     geoBoundaries release's district set
 *   - "Nankana Sahib" (Punjab) — a 2005-created district, same reason
 *   - "Sujawal" (Sindh) — a 2013-created district, same reason
 *   - "Mirpur", "Kotli" (Capital/AJK/GB) — AJK isn't subdivided in this
 *     dataset; only "Muzaffarabad" is mapped to the single unified "Azad
 *     Kashmir" polygon (mapping all three there would silently overwrite
 *     each other in the shapeName->district lookup, so Mirpur/Kotli are left
 *     unmapped and rendered as "No data" instead)
 */
export const DISTRICT_NAME_TO_SHAPE_NAME = {
  Vehari: 'Vihari', // dataset spelling
  Sheikhupura: 'Sheikhpura', // dataset spelling (missing "u")
  'Shaheed Benazirabad': 'Nawabshah', // dataset uses the pre-2008 name
  Islamabad: 'Islamabad Capital Territory',
  Muzaffarabad: 'Azad Kashmir', // AJK isn't subdivided in this dataset — approximates the whole region
  'Dir Lower': 'Lower Dir', // dataset word order
  'Dir Upper': 'Upper Dir', // dataset word order
  Jaffarabad: 'Jafarabad', // dataset spelling (single "f")
  'Naushahro Feroze': 'Naushehro Feroze', // dataset spelling
};

export function shapeNameFor(districtName) {
  return DISTRICT_NAME_TO_SHAPE_NAME[districtName] || districtName;
}
