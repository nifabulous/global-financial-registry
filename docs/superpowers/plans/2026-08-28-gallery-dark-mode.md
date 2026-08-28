# Gallery Dark Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an accessible, persistent System/Light/Dark theme selector to the dependency-free logo gallery while preserving all registry behavior.

**Architecture:** Keep theme state in a focused `web/theme.js` module with pure normalization, resolution, storage, and attribute helpers. `web/theme-ui.js` owns testable DOM binding while `web/app.js` supplies the page elements; a guarded head bootstrap prevents first-paint flashes. CSS custom properties provide the light palette, explicit dark overrides, and OS-driven dark mode when no override exists.

**Tech Stack:** Native browser ES modules, CSS custom properties/media queries, `localStorage`, Node's built-in `node:test`, and the existing Python contract tests.

## Global Constraints

- The default theme is `System`, following the operating system preference.
- Supported user choices are exactly `System`, `Light`, and `Dark`.
- Unknown or unsafe stored values normalize to `system` before storage or DOM attribute use.
- Storage read/write failures must not break the gallery; current-session selection still applies.
- The theme is presentation state only and must not alter registry data, asset URLs, rights labels, filters, or responsive layout.
- Do not add a framework, external package, remote asset, server endpoint, or logo-data change.
- Preserve keyboard accessibility, at least 44px control height, visible focus, and reduced-motion behavior.

---

### Task 1: Add the pure theme state module

**Files:**
- Create: `web/theme.test.mjs`
- Create: `web/theme.js`

**Interfaces:**
- Produces `THEME_STORAGE_KEY`, `normalizeTheme(value)`, `resolveTheme(theme, prefersDark)`, `themeAttribute(theme)`, `readStoredTheme(storage)`, `writeStoredTheme(storage, theme)`, and `applyThemeAttribute(documentElement, theme)` for the app and later tests.
- `normalizeTheme` returns one of the literal strings `system`, `light`, or `dark`.
- `resolveTheme` returns the effective literal `light` or `dark`.
- `themeAttribute` returns `null` for `system`, otherwise the explicit theme.
- `readStoredTheme` and `writeStoredTheme` use the shared key and swallow storage failures.

- [x] **Step 1: Write the failing theme tests**

Create `web/theme.test.mjs` with tests that import the not-yet-created module:

```js
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
```

- [x] **Step 2: Run the theme tests to verify the expected failure**

Run: `node --test web/theme.test.mjs`

Expected: FAIL with an `ERR_MODULE_NOT_FOUND` for `web/theme.js`; no production module exists yet.

- [x] **Step 3: Implement the minimal pure module**

Create `web/theme.js` with the exact safe interfaces:

```js
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
```

- [x] **Step 4: Run the theme tests to verify green**

Run: `node --test web/theme.test.mjs`

Expected: all six theme tests pass.

- [x] **Step 5: Commit the focused module**

```bash
git add web/theme.js web/theme.test.mjs
git commit -m "feat: add gallery theme state helpers"
```

### Task 2: Add the selector, first-paint bootstrap, and app wiring

**Files:**
- Modify: `tests/test_gallery.py`
- Modify: `web/index.html`
- Modify: `web/app.js`
- Create: `web/theme-ui.js`
- Create: `web/theme-ui.test.mjs`

**Interfaces:**
- Consumes the helpers from `web/theme.js` through `web/theme-ui.js`.
- Produces a `#theme-select` control with values `system`, `light`, and `dark`.
- The app initializes from storage, applies the safe document attribute, and persists every valid selection.

- [x] **Step 1: Add failing gallery contract assertions**

Extend `tests/test_gallery.py` with `THEME_PATH = ROOT / "web" / "theme.js"` and assertions in the existing gallery tests:

```python
assert THEME_PATH.is_file()
assert 'id="theme-select"' in index
assert 'value="system"' in index
assert 'value="light"' in index
assert 'value="dark"' in index
assert 'gfr-gallery-theme' in index
assert index.index("localStorage.getItem") < index.index('<link rel="stylesheet" href="styles.css">')
assert 'from "./theme-ui.js"' in app
assert "theme-select" in app
```

Run: `pytest tests/test_gallery.py -q`

Expected: FAIL because the selector, bootstrap key, and app import do not exist yet.

- [x] **Step 2: Add the accessible selector and guarded head bootstrap**

In `web/index.html`, place this guarded script before the stylesheet link so explicit overrides are available before first paint:

```html
<script>
  (() => {
    try {
      const saved = localStorage.getItem("gfr-gallery-theme");
      if (saved === "light" || saved === "dark") {
        document.documentElement.dataset.theme = saved;
      }
    } catch {
      // System theme remains the safe fallback when storage is unavailable.
    }
  })();
</script>
```

Add a labeled control after the lede and before the rights notice:

```html
<div class="theme-control">
  <label for="theme-select">Theme</label>
  <select id="theme-select" aria-describedby="theme-hint">
    <option value="system">System</option>
    <option value="light">Light</option>
    <option value="dark">Dark</option>
  </select>
  <span id="theme-hint" class="visually-hidden">System follows your device appearance.</span>
</div>
```

- [x] **Step 3: Wire the selector into `web/app.js`**

Keep the testable `getThemeStorage`, `initializeTheme`, and `bindThemeControl` helpers in `web/theme-ui.js`. Import those helpers in `web/app.js`, add `themeSelect` to `elements`, and call theme setup before `bootstrap()` so it remains independent from registry loading and filter controls:

```js
const themeStorage = getThemeStorage(window);
initializeTheme({
  storage: themeStorage,
  documentElement: document.documentElement,
  themeSelect: elements.themeSelect,
});
bindThemeControl({
  storage: themeStorage,
  documentElement: document.documentElement,
  themeSelect: elements.themeSelect,
});
```

Call `initializeTheme()` and `bindThemeControl()` before the existing registry `bootstrap()` call, keeping theme setup independent from network loading and filter controls.

- [x] **Step 4: Verify the selector wiring is green**

Run: `pytest tests/test_gallery.py -q && node --check web/app.js && node --check web/theme.js`

Expected: gallery contract tests pass and both modules parse successfully.

- [x] **Step 5: Commit the UI wiring**

```bash
git add tests/test_gallery.py web/index.html web/app.js
git commit -m "feat: add persistent gallery theme selector"
```

### Task 3: Add the dark palette and accessible control styling

**Files:**
- Modify: `tests/test_gallery.py`
- Modify: `web/styles.css`

**Interfaces:**
- CSS keeps the current light palette as the default.
- `data-theme="light"` and `data-theme="dark"` are explicit overrides.
- When no explicit override exists, `prefers-color-scheme: dark` selects the dark palette.

- [x] **Step 1: Add failing CSS contract assertions**

Add these assertions to `test_gallery_files_and_accessibility_shell_exist`:

```python
assert 'data-theme="dark"' in styles
assert '@media (prefers-color-scheme: dark)' in styles
assert 'color-scheme: dark' in styles
assert '--color-preview' in styles
assert '.visually-hidden' in styles
```

Run: `pytest tests/test_gallery.py::test_gallery_files_and_accessibility_shell_exist -q`

Expected: FAIL because the dark selectors, semantic preview token, and visually-hidden utility are not present.

- [x] **Step 2: Add semantic color tokens and dark overrides**

Refactor hard-coded presentation colors in `web/styles.css` to use tokens, preserving the current light values:

```css
:root {
  color-scheme: light;
  --color-visited: #5f3b73;
  --color-preview: #f0ede7;
  --color-loading: #eeeae2;
  --color-contrast: #ffffff;
}

:root[data-theme="dark"] {
  color-scheme: dark;
  --color-canvas: #141311;
  --color-surface: #201d19;
  --color-ink: #f5f1e9;
  --color-muted: #b8b0a5;
  --color-border: #4a453e;
  --color-accent: #d96a4d;
  --color-accent-strong: #f18a67;
  --color-warning-surface: #3b2e1b;
  --color-error-surface: #3a2422;
  --color-visited: #d2a4da;
  --color-preview: #f0ede7;
  --color-loading: #28251f;
  --color-contrast: #171311;
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]):not([data-theme="dark"]) {
    color-scheme: dark;
    --color-canvas: #141311;
    --color-surface: #201d19;
    --color-ink: #f5f1e9;
    --color-muted: #b8b0a5;
    --color-border: #4a453e;
    --color-accent: #d96a4d;
    --color-accent-strong: #f18a67;
    --color-warning-surface: #3b2e1b;
    --color-error-surface: #3a2422;
    --color-visited: #d2a4da;
    --color-preview: #f0ede7;
    --color-loading: #28251f;
    --color-contrast: #171311;
  }
}
```

Use the tokens for `a:visited`, skip-link and button foregrounds, logo preview background, and loading-card background. Add the labeled control and utility styling without changing existing breakpoints:

```css
.theme-control { display: grid; gap: var(--space-1); width: min(100%, 12rem); color: var(--color-muted); font-size: 0.85rem; font-weight: 700; }
.theme-control select { min-height: 44px; }
.visually-hidden { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
```

- [x] **Step 3: Verify CSS and accessibility contracts**

Run: `pytest tests/test_gallery.py -q`

Expected: all gallery contract tests pass.

- [x] **Step 4: Commit the palette**

```bash
git add tests/test_gallery.py web/styles.css
git commit -m "feat: add accessible gallery dark palette"
```

### Task 4: Integrate CI coverage, documentation, and full verification

**Files:**
- Modify: `.github/workflows/registry-core.yml`
- Modify: `README.md`
- Modify: `data/gallery.json`
- Create: `scripts/build_gallery_data.py`
- Create: `src/financial_registry/gallery_data.py`

**Interfaces:**
- CI runs the theme behavior tests alongside the existing gallery tests and verifies the generated gallery projection.
- Local gallery documentation explains that the selector follows System, Light, and Dark choices and persists explicit overrides.

- [x] **Step 1: Add the CI command and documentation assertions**

Update `.github/workflows/registry-core.yml` with:

```yaml
      - run: node --test web/theme.test.mjs
```

Add a short README sentence in the local gallery section: `Use the Theme selector to follow your system preference or choose a persistent Light/Dark override.`

- [x] **Step 2: Run focused verification**

Run:

```bash
node --test web/theme.test.mjs web/gallery-core.test.mjs
node --check web/app.js
node --check web/theme.js
pytest tests/test_gallery.py -q
```

Expected: all Node tests, syntax checks, and gallery contract tests pass.

- [x] **Step 3: Run the complete project verification**

Run:

```bash
PYTHONPATH=src .venv/bin/pytest --cov=financial_registry --cov-fail-under=85 -q
.venv/bin/ruff check src tests scripts
PYTHONPATH=src .venv/bin/python scripts/check_logo_manifest.py data/registry-with-logos.json data/logo-manifest.json
PYTHONPATH=src .venv/bin/financial-registry validate data/registry-with-logos.json
git diff --check origin/main...HEAD
```

Expected: the Python suite reaches the existing 85% coverage gate, Ruff reports no violations, manifest and registry validation pass, and the diff has no whitespace errors.

- [ ] **Step 4: Perform the local manual acceptance pass**

Serve the gallery with `python3 -m http.server 8123`, open `http://127.0.0.1:8123/web/`, and verify:

1. System follows the OS palette and changes live when the OS preference changes.
2. Light and Dark apply immediately and persist after reload.
3. A malformed stored value behaves as System and never creates an arbitrary `data-theme` value.
4. The selector is keyboard reachable, at least 44px tall, has a visible focus ring, and native controls remain readable in both palettes.
5. Logo cards, rights notices, warnings, empty states, loading states, and error states remain legible; reduced-motion CSS remains honored.

Automated HTTP endpoint smoke checks and the Node/Python contract suites are complete. The interactive browser/OS-preference pass remains pending because no browser automation is available in this worktree.

- [x] **Step 5: Commit CI and documentation**

```bash
git add .github/workflows/registry-core.yml README.md
git commit -m "test: cover gallery theme behavior in CI"
```

## Post-review hardening

The pre-landing review identified two correctness defects, two robustness gaps, and four maintainability/scale risks. The following changes were folded into the implementation:

- [x] Keep zero-asset manifest serialization valid JSON and reject non-object manifests with `LogoManifestError`.
- [x] Deduplicate broken-preview warnings across card rerenders and reset the session tracker after a successful reload.
- [x] Use a contrast-safe light preview surface in dark mode and centralize the dark palette values.
- [x] Exercise theme initialization and selector persistence through the testable `web/theme-ui.js` module.
- [x] Use locale-independent card ordering and cache normalized search text.
- [x] Generate and verify `data/gallery.json`, a linked-owner projection that avoids downloading the full registry history.
- [x] Bound the rendered card page to 100 items with a Load more control and debounce search input updates.
- [x] Add a contract test tying the early bootstrap storage key to `web/theme.js`.
