import test from "node:test";
import assert from "node:assert/strict";

import {
  THEME_STORAGE_KEY,
  applyThemeAttribute,
  normalizeTheme,
  readStoredTheme,
  resolveTheme,
  themeAttribute,
  writeStoredTheme,
} from "./theme.js";

function storage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    values,
    getItem(key) { return values.has(key) ? values.get(key) : null; },
    setItem(key, value) { values.set(key, String(value)); },
  };
}

test("normalizeTheme accepts only supported values", () => {
  assert.equal(normalizeTheme("system"), "system");
  assert.equal(normalizeTheme("light"), "light");
  assert.equal(normalizeTheme("dark"), "dark");
  assert.equal(normalizeTheme("blue"), "system");
  assert.equal(normalizeTheme(null), "system");
});

test("resolveTheme follows the OS only for the System choice", () => {
  assert.equal(resolveTheme("system", true), "dark");
  assert.equal(resolveTheme("system", false), "light");
  assert.equal(resolveTheme("light", true), "light");
  assert.equal(resolveTheme("dark", false), "dark");
});

test("themeAttribute maps System to no override", () => {
  assert.equal(themeAttribute("system"), null);
  assert.equal(themeAttribute("light"), "light");
  assert.equal(themeAttribute("dark"), "dark");
  assert.equal(themeAttribute("invalid"), null);
});

test("theme values round-trip through storage under the shared key", () => {
  const store = storage();
  assert.equal(writeStoredTheme(store, "dark"), "dark");
  assert.equal(store.values.get(THEME_STORAGE_KEY), "dark");
  assert.equal(readStoredTheme(store), "dark");
  assert.equal(writeStoredTheme(store, "invalid"), "system");
  assert.equal(readStoredTheme(store), "system");
});

test("storage failures fall back without escaping", () => {
  const broken = {
    getItem() { throw new Error("blocked"); },
    setItem() { throw new Error("blocked"); },
  };
  assert.equal(readStoredTheme(broken), "system");
  assert.equal(writeStoredTheme(broken, "dark"), "dark");
});

test("applyThemeAttribute sets only explicit safe attributes", () => {
  const root = { dataset: { theme: "dark" } };
  assert.equal(applyThemeAttribute(root, "light"), "light");
  assert.equal(root.dataset.theme, "light");
  assert.equal(applyThemeAttribute(root, "system"), "system");
  assert.equal("theme" in root.dataset, false);
});
