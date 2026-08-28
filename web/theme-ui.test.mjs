import test from "node:test";
import assert from "node:assert/strict";

import { THEME_STORAGE_KEY } from "./theme.js";
import {
  bindThemeControl,
  getThemeStorage,
  initializeTheme,
} from "./theme-ui.js";

function storage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    values,
    getItem(key) { return values.has(key) ? values.get(key) : null; },
    setItem(key, value) { values.set(key, String(value)); },
  };
}

function select() {
  return {
    value: "system",
    listeners: new Map(),
    addEventListener(type, listener) { this.listeners.set(type, listener); },
  };
}

test("initializeTheme applies persisted choice and synchronizes the selector", () => {
  const root = { dataset: {} };
  const themeSelect = select();

  const theme = initializeTheme({
    storage: storage({ [THEME_STORAGE_KEY]: "dark" }),
    documentElement: root,
    themeSelect,
  });

  assert.equal(theme, "dark");
  assert.equal(root.dataset.theme, "dark");
  assert.equal(themeSelect.value, "dark");
});

test("bindThemeControl persists and applies a safe selector change", () => {
  const root = { dataset: {} };
  const themeSelect = select();
  const store = storage();

  bindThemeControl({ storage: store, documentElement: root, themeSelect });
  themeSelect.value = "light";
  themeSelect.listeners.get("change")();

  assert.equal(store.values.get(THEME_STORAGE_KEY), "light");
  assert.equal(root.dataset.theme, "light");
  assert.equal(themeSelect.value, "light");
});

test("getThemeStorage contains unavailable storage failures", () => {
  const windowObject = {
    get localStorage() { throw new Error("blocked"); },
  };

  assert.equal(getThemeStorage(windowObject), null);
});
