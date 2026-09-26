import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// Unit tests only (pure logic in src/lib and src/i18n) — no browser needed.
export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
