export const THEME_STORAGE_KEY = "gfr-gallery-theme";
const THEMES = new Set(["system", "light", "dark"]);

export function normalizeTheme(value) {
  return typeof value === "string" && THEMES.has(value) ? value : "system";
}

export function resolveTheme(theme, prefersDark) {
  const normalized = normalizeTheme(theme);
  return normalized === "system" ? (prefersDark ? "dark" : "light") : normalized;
}

export function themeAttribute(theme) {
  const normalized = normalizeTheme(theme);
  return normalized === "system" ? null : normalized;
}

export function readStoredTheme(storage) {
  if (!storage || typeof storage.getItem !== "function") return "system";
  try {
    return normalizeTheme(storage.getItem(THEME_STORAGE_KEY));
  } catch {
    return "system";
  }
}

export function writeStoredTheme(storage, theme) {
  const normalized = normalizeTheme(theme);
  if (storage && typeof storage.setItem === "function") {
    try {
      storage.setItem(THEME_STORAGE_KEY, normalized);
    } catch {
      // Private browsing and restrictive storage policies are valid fallbacks.
    }
  }
  return normalized;
}

export function applyThemeAttribute(documentElement, theme) {
  const normalized = normalizeTheme(theme);
  const attribute = themeAttribute(normalized);
  if (!documentElement?.dataset) return normalized;
  if (attribute) documentElement.dataset.theme = attribute;
  else delete documentElement.dataset.theme;
  return normalized;
}
