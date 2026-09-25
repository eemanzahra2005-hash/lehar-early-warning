/**
 * Plain-English "why" line for a recommendation, built from simple, fixed
 * thresholds on real input values — explicitly rule-based, not an LLM and
 * not a learned explanation. Shared by the dashboard and predict views.
 */

export function describeFactors({ soil_moisture_pct, evapotranspiration_mm, rainfall_mm, temperature_c }) {
  const parts = [];
  let demandScore = 0;

  if (soil_moisture_pct < 30) {
    parts.push('soil moisture low');
    demandScore += 1;
  } else if (soil_moisture_pct > 65) {
    parts.push('soil moisture high');
    demandScore -= 1;
  } else {
    parts.push('soil moisture moderate');
  }

  if (evapotranspiration_mm > 7) {
    parts.push('high ET0');
    demandScore += 1;
  } else if (evapotranspiration_mm < 4) {
    parts.push('low ET0');
    demandScore -= 1;
  } else {
    parts.push('moderate ET0');
  }

  if (rainfall_mm < 2) {
    parts.push('low rain chance');
    demandScore += 1;
  } else if (rainfall_mm > 8) {
    parts.push('recent heavy rain');
    demandScore -= 1;
  } else {
    parts.push('some recent rain');
  }

  if (temperature_c > 35) {
    parts.push('hot conditions');
    demandScore += 1;
  }

  let conclusion = 'moderate irrigation demand';
  if (demandScore >= 2) conclusion = 'higher irrigation demand';
  else if (demandScore <= -1) conclusion = 'lower irrigation demand';

  const factorText = parts.slice(0, 3).join(' + ');
  return `${factorText[0].toUpperCase()}${factorText.slice(1)} → ${conclusion}.`;
}

/**
 * Weather-only irrigation demand level for the dashboard's context header
 * (soil moisture isn't known there — that's only produced by running an
 * actual prediction, see describeFactors() above). Fixed-threshold rules,
 * scored 0-4, never an invented number:
 *   +2  ET0 > 6mm            (+1 if 3-6mm)
 *   +1  humidity < 30%       (dry air pulls more irrigation demand)
 *   +1  rainfall < 1mm       (-1 if > 5mm, recent heavy rain)
 *   +1  temperature > 35°C
 * score >= 3 -> HIGH, score >= 1 -> MODERATE, else LOW.
 */
export function demandLevel({ temperature_c, humidity_pct, rainfall_mm, evapotranspiration_mm }) {
  let score = 0;
  if (evapotranspiration_mm > 6) score += 2;
  else if (evapotranspiration_mm > 3) score += 1;
  if (humidity_pct < 30) score += 1;
  if (rainfall_mm < 1) score += 1;
  else if (rainfall_mm > 5) score -= 1;
  if (temperature_c > 35) score += 1;

  if (score >= 3) return 'HIGH';
  if (score >= 1) return 'MODERATE';
  return 'LOW';
}

function humidityDescriptor(pct) {
  if (pct < 30) return 'dry air';
  if (pct > 60) return 'humid air';
  return 'moderate humidity';
}

function et0Descriptor(mm) {
  if (mm > 6) return 'elevated ET0';
  if (mm > 3) return 'moderate ET0';
  return 'low ET0';
}

/** Builds the dashboard's smart status line from real current weather —
 * plain sentence assembly from fixed rules, never model- or LLM-generated. */
export function buildContextLine(district, weather, now = new Date()) {
  const weekday = now.toLocaleDateString(undefined, { weekday: 'long' });
  const time = now.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false });
  return {
    text: `${weekday}, ${time} — ${district}: ${weather.temperature_c.toFixed(0)}°C, ${humidityDescriptor(weather.humidity_pct)}, ${et0Descriptor(weather.evapotranspiration_mm)}.`,
    level: demandLevel(weather),
  };
}
