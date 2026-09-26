"use client";

import { useMemo } from "react";
import { encode } from "uqr";

/**
 * A QR code for a URL, drawn as one SVG path (uqr does the encoding, ~10 KB,
 * no canvas). Always dark modules on white with a quiet zone: phone cameras
 * scan that reliably, whatever the page theme.
 */
export function QrCode({ value, label, className = "h-44 w-44" }: { value: string; label: string; className?: string }) {
  const { size, path } = useMemo(() => {
    const qr = encode(value, { ecc: "M", border: 2 });
    let d = "";
    qr.data.forEach((row, y) =>
      row.forEach((dark, x) => {
        if (dark) d += `M${x} ${y}h1v1h-1z`;
      }),
    );
    return { size: qr.size, path: d };
  }, [value]);

  return (
    <svg viewBox={`0 0 ${size} ${size}`} className={`rounded-xl bg-white p-1 ${className}`} role="img" aria-label={label} shapeRendering="crispEdges">
      <path d={path} fill="#0b1220" />
    </svg>
  );
}
