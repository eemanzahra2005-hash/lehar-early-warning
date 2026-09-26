"use client";

// Leaflet touches `window` at import time, so this component is only ever
// loaded through next/dynamic with ssr:false (see app/map/page.tsx).
import "leaflet/dist/leaflet.css";
import type { Feature, FeatureCollection, Geometry } from "geojson";
import type { Layer, PathOptions } from "leaflet";
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
}

function FitBounds({ data }: { data: FeatureCollection<Geometry, ShapeProps> }) {
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
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [8, 8] });
  }, [data, map]);
  return null;
}

export default function DistrictMap({ levelByDistrict, districts, selected, onSelect, describe, noDataLabel }: DistrictMapProps) {
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

  if (failed) return <p role="alert">Map shapes could not be loaded.</p>;
  if (!geo) return <div className="h-full w-full animate-pulse bg-slate-100" />;

  const style = (feature?: Feature<Geometry, ShapeProps>): PathOptions => {
    const district = feature ? districtForShape(feature.properties.shapeName, districts) : null;
    const level = district ? levelByDistrict[district] : undefined;
    const isSelected = district !== null && district === selected;
    return {
      fillColor: level !== undefined ? levelToken(level).bg : "#e2e8f0",
      fillOpacity: level !== undefined ? 0.9 : 0.5,
      color: isSelected ? "#2563eb" : "#334155",
      weight: isSelected ? 3 : 0.6,
      // Unmatched shapes (outside LEHAR's district list) are hatched grey.
      dashArray: district ? undefined : "2 3",
    };
  };

  const onEachFeature = (feature: Feature<Geometry, ShapeProps>, layer: Layer) => {
    const district = districtForShape(feature.properties.shapeName, districts);
    // Tooltip text always names the level in words, never colour alone.
    layer.bindTooltip(district ? describe(district) : `${feature.properties.shapeName} — ${noDataLabel}`, { sticky: true });
    if (district) layer.on("click", () => onSelect(district));
  };

  return (
    <MapContainer center={[30.4, 69.3]} zoom={5} scrollWheelZoom={false} className="h-full w-full" attributionControl={false}>
      <GeoJSON key={styleKey} data={geo} style={style} onEachFeature={onEachFeature} />
      <FitBounds data={geo} />
    </MapContainer>
  );
}
