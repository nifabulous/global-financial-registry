import {
  applyThemeAttribute,
  readStoredTheme,
  writeStoredTheme,
} from "./theme.js";

export function getThemeStorage(windowObject) {
  try {
    return windowObject?.localStorage ?? null;
  } catch {
    return null;
  }
}

export function initializeTheme({ storage, documentElement, themeSelect }) {
  const theme = readStoredTheme(storage);
  applyThemeAttribute(documentElement, theme);
  if (themeSelect) themeSelect.value = theme;
  return theme;
}

export function bindThemeControl({ storage, documentElement, themeSelect }) {
  if (!themeSelect) return null;
  const handleChange = () => {
    const theme = writeStoredTheme(storage, themeSelect.value);
    applyThemeAttribute(documentElement, theme);
    themeSelect.value = theme;
    return theme;
  };
  themeSelect.addEventListener("change", handleChange);
  return handleChange;
}
