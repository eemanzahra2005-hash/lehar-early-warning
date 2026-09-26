import { describe, expect, it } from "vitest";
import { en, placeholders, translate, ur, type DictKey } from "../dictionary";

const keys = Object.keys(en) as DictKey[];

describe("i18n dictionary", () => {
  it("has exactly the same keys in English and Urdu", () => {
    expect(Object.keys(ur).sort()).toEqual([...keys].sort());
  });

  it("has no empty values in either language", () => {
    for (const key of keys) {
      expect(en[key].trim(), `en ${key}`).not.toBe("");
      expect(ur[key].trim(), `ur ${key}`).not.toBe("");
    }
  });

  it("uses the same {placeholders} in both languages", () => {
    for (const key of keys) {
      expect(placeholders(ur[key]), key).toEqual(placeholders(en[key]));
    }
  });

  it("actually translates UI text into Urdu script", () => {
    // Guards against copy-pasting English into the Urdu table.
    const arabicScript = /[؀-ۿ]/;
    const untranslated = keys.filter((key) => !arabicScript.test(ur[key]));
    // Only language-neutral strings (brand toggle, units) may stay Latin.
    expect(untranslated.sort()).toEqual(["lang.toggle", "map.unit"]);
  });

  it("carries the mandated disclaimer verbatim (CLAUDE.md rule 12)", () => {
    expect(en.disclaimer).toBe("Research advisory — NDMA/PMD/PDMA official warnings are authoritative.");
    // Same text as DISCLAIMER_UR in backend/app/services/alerts/levels.py.
    expect(ur.disclaimer).toBe("تحقیقی مشورہ — این ڈی ایم اے/پی ایم ڈی/پی ڈی ایم اے کی سرکاری وارننگ ہی مستند ہے۔");
  });

  it("fills placeholders and leaves unknown ones visible", () => {
    expect(translate("en", "common.level", { n: 3 })).toBe("Level 3");
    expect(translate("ur", "common.level", { n: 3 })).toBe("درجہ 3");
    expect(translate("en", "board.alertingDistricts", { n: 2 })).toBe("2 of {total} districts under an alert");
  });
});
