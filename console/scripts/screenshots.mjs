// Captures the console's main pages into ../docs/screenshots/ (phone + desktop).
//
// Optional tooling: Playwright is deliberately NOT a dependency of the
// console (it would add to every `npm ci` on CI and Vercel). To run it:
//
//   cd console
//   npm run build && npm start              # console on http://localhost:3000
//   npm i --no-save playwright@1.63.0       # once; package.json stays untouched
//   npx playwright install chromium         # once, if no browser is installed
//   npm run screenshots                     # or: node scripts/screenshots.mjs [baseUrl]
//
// The LEHAR backend must be running too: the screenshots show whatever the
// API really returns (the console never shows made-up data, and neither do
// its screenshots).

import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const BASE = (process.argv[2] ?? process.env.CONSOLE_URL ?? "http://localhost:3000").replace(/\/+$/, "");
const OUT = resolve(dirname(fileURLToPath(import.meta.url)), "../../docs/screenshots");
const PAGES = [
  { name: "home", path: "/" },
  { name: "map", path: "/map" },
  { name: "alerts", path: "/alerts" },
  { name: "subscribe", path: "/subscribe" },
];
const VIEWPORTS = [
  { name: "phone", width: 390, height: 844 },
  { name: "desktop", width: 1280, height: 900 },
];

let chromium;
try {
  ({ chromium } = await import("playwright"));
} catch {
  console.log("Playwright is not installed, so no screenshots were taken (this is optional).");
  console.log("Install it without touching package.json:  npm i --no-save playwright@1.63.0 && npx playwright install chromium");
  process.exit(0);
}

let browser;
try {
  browser = await chromium.launch();
} catch {
  // No bundled browser downloaded: fall back to an installed Chrome.
  try {
    browser = await chromium.launch({ channel: "chrome" });
  } catch {
    console.log("No Chromium found. Run:  npx playwright install chromium  (skipping screenshots)");
    process.exit(0);
  }
}

mkdirSync(OUT, { recursive: true });
for (const viewport of VIEWPORTS) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 2, reducedMotion: "reduce" });
  const page = await context.newPage();
  for (const { name, path } of PAGES) {
    await page.goto(BASE + path, { waitUntil: "load" });
    // Scroll through once so lazy parts (the home mini-map) load, then settle.
    await page.evaluate(async () => {
      for (let y = 0; y < document.body.scrollHeight; y += 600) {
        window.scrollTo(0, y);
        await new Promise((r) => setTimeout(r, 80));
      }
      window.scrollTo(0, 0);
    });
    await page.waitForTimeout(2500);
    const file = resolve(OUT, `${name}-${viewport.name}.png`);
    await page.screenshot({ path: file, fullPage: viewport.name === "phone" });
    console.log("saved", file);
  }
  await context.close();
}
await browser.close();
