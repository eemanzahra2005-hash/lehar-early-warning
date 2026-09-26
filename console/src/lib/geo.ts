/**
 * Maps LEHAR's 107 canonical district names (backend/ml/districts.py) onto the
 * `shapeName` of public/geo/pakistan_districts.geojson (geoBoundaries PAK ADM2).
 *
 * Ported verbatim from frontend/js/districtGeoMapping.js so the console and
 * the local frontend draw the same map. Known gaps (no polygon in this
 * dataset): Larkana, Chiniot, Nankana Sahib, Sujawal, Mirpur, Kotli. The map
 * page lists them next to the map instead of silently hiding them.
 */

export const DISTRICT_NAME_TO_SHAPE_NAME: Record<string, string> = {
  Vehari: "Vihari",
  Sheikhupura: "Sheikhpura",
  "Shaheed Benazirabad": "Nawabshah",
  Islamabad: "Islamabad Capital Territory",
  Muzaffarabad: "Azad Kashmir",
  "Dir Lower": "Lower Dir",
  "Dir Upper": "Upper Dir",
  Jaffarabad: "Jafarabad",
  "Naushahro Feroze": "Naushehro Feroze",
};

export function shapeNameFor(district: string): string {
  return DISTRICT_NAME_TO_SHAPE_NAME[district] ?? district;
}

/** Reverse lookup: polygon shapeName -> LEHAR district name (or null). */
export function districtForShape(shapeName: string, districts: string[]): string | null {
  for (const district of districts) {
    if (shapeNameFor(district) === shapeName) return district;
  }
  return null;
}
