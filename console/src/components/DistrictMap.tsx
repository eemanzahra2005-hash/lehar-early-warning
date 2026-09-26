"use client";

// Leaflet touches `window` at import time, so this component is only ever
// loaded through next/dynamic with ssr:false (see app/map/page.tsx).
import "leaflet/dist/leaflet.css";
import type { Feature, FeatureCollection, Geometry } from "geojson";
import type { Layer, Path, PathOptions } from "leaflet";
import { latLngBounds } from "leaflet";
import { useEffect, useMemo, useState } from "react";
import { GeoJSON, MapContainer, useMap } from "react-leaflet";
import { districtForShape } from "@/lib/geo";
import { levelToken } from "@/lib/levels";

type ShapeProps = { shapeName: string };

interface DistrictMapProps {
  /** Current level per LEHAR district name (from GET /alerts/active). */
  levelByDistrict: Record<string, number>;
  districts: string[];
  selected: string | null;
  onSelect: (district: string) => void;
  /** Accessible text for a district's tooltip, e.g. "Multan — Level 3 · Warning". */
  describe: (district: string) => string;
  noDataLabel: string;
  /** Pixels hidden by the floating district panel (0 when it is closed). */
  padEnd?: number;
  rtl?: boolean;
}

/** Fits the country in view, leaving `padEnd` px free on the side the district panel covers. */
function FitBounds({ data, padEnd, rtl }: { data: FeatureCollection<Geometry, ShapeProps>; padEnd: number; rtl: boolean }) {
  const map = useMap();
  useEffect(() => {
    const bounds = latLngBounds([]);
    for (const feature of data.features) {
      const walk = (coords: unknown): void => {
        if (Array.isArray(coords) && typeof coords[0] === "number") bounds.extend([coords[1] as number, coords[0] as number]);
        else if (Array.isArray(coords)) coords.forEach(walk);
      };
      if ("coordinates" in feature.geometry) walk(feature.geometry.coordinates);
    }
    if (!bounds.isValid()) return;
    const side: [number, number] = [16 + padEnd, 16];
    map.fitBounds(bounds, rtl ? { paddingTopLeft: side, paddingBottomRight: [16, 16] } : { paddingTopLeft: [16, 16], paddingBottomRight: side });
  }, [data, map, padEnd, rtl]);
  return null;
}

export default function DistrictMap({ levelByDistrict, districts, selected, onSelect, describe, noDataLabel, padEnd = 0, rtl = false }: DistrictMapProps) {
  const [geo, setGeo] = useState<FeatureCollection<Geometry, ShapeProps> | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    fetch("/geo/pakistan_districts.geojson")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(setGeo)
      .catch(() => setFailed(true));
  }, []);

  // GeoJSON layers do not re-style on prop change, so a key built from the
  // data forces a redraw when levels or the selection change.
  const styleKey = useMemo(() => JSON.stringify(levelByDistrict) + (selected ?? ""), [levelByDistrict, selected]);

  if (failed) return <p role="alert" className="grid h-full place-items-center text-muted">Map shapes could not be loaded.</p>;
  if (!geo) return <div className="skeleton h-full w-full rounded-none" />;

  const style = (feature?: Feature<Geometry, ShapeProps>): PathOptions => {
    const district = feature ? districtForShape(feature.properties.shapeName, districts) : null;
    const level = district ? levelByDistrict[district] : undefined;
    const token = level !== undefined ? levelToken(level) : null;
    const isSelected = district !== null && district === selected;
    const alerting = level !== undefined && level >= 2;
    return {
      // Official level colour as the fill; calm L1 is only a faint white wash
      // on the dark map, so the districts that DO have an alert stand out.
      fillColor: token ? token.bg : "#0e1524",
      fillOpacity: !token ? 0.2 : level === 1 ? 0.12 : 0.82,
      color: isSelected ? "#5eead4" : token ? token.ink : "#94a0b2",
      opacity: isSelected || alerting ? 1 : 0.4,
      weight: isSelected ? 3 : alerting ? 1.4 : 0.6,
      // Unmatched shapes (outside LEHAR's district list) are dashed.
      dashArray: district ? undefined : "2 3",
      className: "district-path",
    };
  };

  const onEachFeature = (feature: Feature<Geometry, ShapeProps>, layer: Layer) => {
    const district = districtForShape(feature.properties.shapeName, districts);
    // Tooltip text always names the level in words, never colour alone.
    layer.bindTooltip(district ? describe(district) : `${feature.properties.shapeName} — ${noDataLabel}`, {
      sticky: true,
      className: "lehar-tip",
      direction: "top",
      offset: [0, -8],
    });
    if (!district) return;
    const path = layer as Path;
    layer.on("click", () => onSelect(district));
    // Hover glow: a bright outline pulled to the front, restored on leave.
    layer.on("mouseover", () => {
      path.setStyle({ weight: 2.5, color: "#ffffff", opacity: 1 });
      path.bringToFront();
    });
    layer.on("mouseout", () => path.setStyle(style(feature)));
  };

  return (
    <MapContainer center={[30.4, 69.3]} zoom={5} zoomSnap={0.25} scrollWheelZoom={false} className="h-full w-full" attributionControl={false}>
      <GeoJSON key={styleKey} data={geo} style={style} onEachFeature={onEachFeature} />
      <FitBounds data={geo} padEnd={padEnd} rtl={rtl} />
    </MapContainer>
  );
}
