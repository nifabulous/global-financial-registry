# Bank Logo Gallery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task with checkpoints.

**Goal:** Build a dependency-free local HTML gallery that visually inspects every committed logo asset in `data/registry-with-logos.json` while preserving registry ownership, provenance, format, and rights metadata.

**Architecture:** `web/index.html` provides the semantic shell and controls, `web/styles.css` provides the editorial catalog layout, and `web/app.js` fetches the derived registry, joins assets to institutions/brands by `owner_id`, resolves local binaries from `staging_path`, and renders filtered cards with DOM APIs. A Python test module checks the static contract and verifies that every registry asset resolves to a local file; browser behavior is verified with a local HTTP smoke test.

**Tech Stack:** Vanilla HTML, CSS, and JavaScript; Python standard library and pytest for structural/data-integrity tests; the existing Python registry validator, Ruff, and pytest suite.

## Global Constraints

- Use no frontend framework, bundler, backend, CDN, icon package, or third-party runtime dependency.
- Load `../data/registry-with-logos.json` at runtime from `web/index.html`.
- Build one card per asset and join owners by `asset.owner_id`; never hardcode logo metadata.
- Resolve local binaries from `asset.staging_path` under `../data/assets`; never fetch a logo binary from a third-party CDN.
- Preserve the distinction between the current total entities, logo assets, unique asset owners, and entities without assets; these values are derived at runtime because enrichment is ongoing.
- Display asset-specific rights and provenance accurately; do not imply a blanket open copyright licence.
- Use DOM APIs and `textContent` for registry values; do not interpolate registry data through `innerHTML`.
- Render only HTTP/HTTPS source links with `target="_blank"` and `rel="noopener noreferrer"`.
- Keep body text at least 16px with a minimum 4.5:1 contrast ratio, provide visible labels, a 44px minimum hit area, a 3px focus outline, and a reduced-motion path.
- The page is served from the repository root with `python3 -m http.server 8000` and opened at `http://localhost:8000/web/`.

---

## File map

- Create `tests/test_gallery.py` for static HTML/JS contract checks and registry-to-local-asset checks.
- Create `web/index.html` for the document shell, controls, state regions, and loading placeholders.
- Create `web/app.js` for registry loading, owner/source joins, safe URL handling, filtering, card rendering, and state transitions.
- Create `web/styles.css` for the editorial catalog visual system, responsive layout, and state styling.
- Modify `README.md` to document the gallery's purpose, coverage limits, rights notice, and local serving command.

## Task 1: Write the failing gallery contract tests

**Files:**
- Create: `tests/test_gallery.py`

**Interfaces:**
- Produces the executable contract for the files and data paths required by later tasks.
- Uses only `pathlib`, `json`, and `re`; no browser dependency is introduced.

- [ ] **Step 1: Add tests that describe the page contract and registry paths**

```python
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "data" / "registry-with-logos.json"
INDEX_PATH = ROOT / "web" / "index.html"
APP_PATH = ROOT / "web" / "app.js"
STYLES_PATH = ROOT / "web" / "styles.css"


def load_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_gallery_files_and_accessibility_shell_exist() -> None:
    index = INDEX_PATH.read_text(encoding="utf-8")
    styles = STYLES_PATH.read_text(encoding="utf-8")

    assert INDEX_PATH.is_file()
    assert STYLES_PATH.is_file()
    assert '<script type="module" src="app.js"></script>' in index
    assert '<link rel="stylesheet" href="styles.css">' in index
    assert 'href="#gallery-content"' in index
    assert 'id="gallery-content"' in index
    assert 'aria-live="polite"' in index
    assert 'id="search-input"' in index
    assert 'id="entity-type-filter"' in index
    assert 'id="country-filter"' in index
    assert 'id="format-filter"' in index
    assert 'id="rights-filter"' in index
    assert 'id="reset-filters"' in index
    assert "--color-canvas" in styles


def test_every_registry_staging_path_resolves_to_a_local_binary() -> None:
    registry = load_registry()

    assert registry["asset_root"] == "assets"
    assert registry["assets"]
    for asset in registry["assets"]:
        staging_path = Path(asset["staging_path"])
        assert not staging_path.is_absolute()
        assert ".." not in staging_path.parts
        local_path = ROOT / "data" / "assets" / staging_path
        assert local_path.is_file(), asset["staging_path"]


def test_gallery_script_uses_safe_dom_and_source_url_guards() -> None:
    app = APP_PATH.read_text(encoding="utf-8")

    assert APP_PATH.is_file()
    assert "../data/registry-with-logos.json" in app
    assert "textContent" in app
    assert "innerHTML" not in app
    assert re.search(r"new URL\(", app)
    assert "noopener" in app
    assert "noopener noreferrer" in app
    assert "https:" in app
    assert "http:" in app


def test_gallery_copy_explains_scope_and_rights() -> None:
    index = INDEX_PATH.read_text(encoding="utf-8")

    assert "identification" in index.lower()
    assert "no blanket open" in index.lower()
    assert "without a logo" in index.lower()
```

- [ ] **Step 2: Run the new test file and verify it fails for the missing frontend**

Run: `pytest tests/test_gallery.py -q`

Expected: FAIL because `web/index.html`, `web/app.js`, and `web/styles.css` do not exist yet.

- [ ] **Step 3: Commit the failing contract tests**

```bash
git add tests/test_gallery.py
git commit -m "test: define logo gallery contract"
```

## Task 2: Add the semantic shell, loading states, and visual tokens

**Files:**
- Create: `web/index.html`
- Create: `web/styles.css`

**Interfaces:**
- Produces the element IDs consumed by `web/app.js` and asserted by `tests/test_gallery.py`.
- Defines CSS variables, responsive layout, focus states, and the initial loading/error/empty containers.

- [ ] **Step 1: Create the HTML shell with the approved information hierarchy**

Create `web/index.html` with this structure and copy:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="description" content="Local visual catalogue of the global financial registry logo assets.">
    <title>Global Financial Registry | Logo gallery</title>
    <link rel="stylesheet" href="styles.css">
    <script type="module" src="app.js"></script>
  </head>
  <body>
    <a class="skip-link" href="#gallery-content">Skip to logo gallery</a>
    <header class="site-header">
      <p class="eyebrow">Global Financial Registry</p>
      <h1>Logo gallery</h1>
      <p class="lede">A local review surface for the logo assets currently present in the registry.</p>
      <p class="rights-notice">
        Logos and trademarks remain the property of their respective owners. Assets are shown for identification;
        no blanket open copyright licence is asserted. See the <a href="../README.md#license">repository licensing policy</a> for details.
      </p>
      <div class="coverage-summary" id="coverage-summary" aria-label="Registry coverage" hidden>
        <div><strong id="entity-count">0</strong><span>entities</span></div>
        <div><strong id="asset-count">0</strong><span>logo assets</span></div>
        <div><strong id="owner-count">0</strong><span>entities with assets</span></div>
        <div><strong id="missing-count">0</strong><span>without a logo</span></div>
      </div>
    </header>

    <main id="gallery-content" class="gallery-main">
      <section class="toolbar" aria-labelledby="filter-heading">
        <div class="section-heading">
          <p class="eyebrow">Find an asset</p>
          <h2 id="filter-heading">Search and filter</h2>
        </div>
        <div class="filter-grid">
          <label class="filter-control filter-control--search" for="search-input">
            Search name or country
            <input id="search-input" type="search" autocomplete="off" placeholder="e.g. Nubank or US">
          </label>
          <label class="filter-control" for="entity-type-filter">
            Entity type
            <select id="entity-type-filter">
              <option value="all">All types</option>
              <option value="institution">Institutions</option>
              <option value="brand">Brands</option>
              <option value="unknown">Unknown owners</option>
            </select>
          </label>
          <label class="filter-control" for="country-filter">
            Country
            <select id="country-filter"><option value="all">All countries</option></select>
          </label>
          <label class="filter-control" for="format-filter">
            Format
            <select id="format-filter">
              <option value="all">All formats</option>
              <option value="svg">SVG</option>
              <option value="png">PNG</option>
              <option value="jpg">JPEG</option>
              <option value="webp">WEBP</option>
            </select>
          </label>
          <label class="filter-control" for="rights-filter">
            Rights status
            <select id="rights-filter"><option value="all">All rights states</option></select>
          </label>
          <button id="reset-filters" class="button button--secondary" type="button">Reset filters</button>
        </div>
      </section>

      <section class="results" aria-labelledby="results-heading">
        <div class="results-heading">
          <div>
            <p class="eyebrow">Current view</p>
            <h2 id="results-heading">Logo assets</h2>
          </div>
          <p id="result-status" class="result-status" role="status" aria-live="polite">Loading logo registry</p>
        </div>
        <div id="partial-warning" class="state state--warning" role="status" hidden></div>
        <div id="fatal-state" class="state state--error" role="alert" hidden></div>
        <div id="empty-state" class="state state--empty" hidden>
          <h3>No logo assets match these filters</h3>
          <p>Try a broader search or reset the filters to return to the full gallery.</p>
          <button class="button" type="button" data-reset-filters>Reset filters</button>
        </div>
        <div id="loading-state" class="logo-grid logo-grid--loading" aria-label="Loading logo previews">
          <div class="loading-card" aria-hidden="true"></div>
          <div class="loading-card" aria-hidden="true"></div>
          <div class="loading-card" aria-hidden="true"></div>
          <div class="loading-card" aria-hidden="true"></div>
          <div class="loading-card" aria-hidden="true"></div>
          <div class="loading-card" aria-hidden="true"></div>
        </div>
        <div id="logo-grid" class="logo-grid" role="list" hidden></div>
      </section>
    </main>

    <footer class="site-footer">
      <p>Read-only local viewer. Registry data and rights decisions remain in the curated release workflow.</p>
    </footer>
  </body>
</html>
```

- [ ] **Step 2: Add the concrete visual system and responsive rules**

Create `web/styles.css` with the following required tokens and rules. Keep the implementation free of gradients, decorative blobs, emoji, external fonts, ornamental shadows, and color-only status indicators.

```css
:root {
  --color-canvas: #f6f3ee;
  --color-surface: #fffdf9;
  --color-ink: #1e211f;
  --color-muted: #5c625d;
  --color-border: #d7d2c8;
  --color-accent: #9f3b23;
  --color-accent-strong: #7f2e1c;
  --color-warning-surface: #fff2dc;
  --color-error-surface: #fbe9e5;
  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.75rem;
  --space-4: 1rem;
  --space-6: 1.5rem;
  --space-8: 2rem;
  --space-12: 3rem;
  --content-width: 1180px;
}

* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background: var(--color-canvas);
  color: var(--color-ink);
  font-family: "Avenir Next", "Trebuchet MS", sans-serif;
  font-size: 1rem;
  line-height: 1.5;
}
h1, h2, h3, p { margin-top: 0; }
h1, h2, h3 { line-height: 1.15; }
h1 { margin-bottom: var(--space-3); font-family: Georgia, "Times New Roman", serif; font-size: clamp(2.5rem, 7vw, 5.75rem); font-weight: 400; letter-spacing: -0.04em; }
h2 { margin-bottom: var(--space-2); font-size: 1.35rem; }
h3 { margin-bottom: var(--space-2); font-size: 1.05rem; }
a { color: var(--color-accent-strong); }
a:visited { color: #5f3b73; }
button, input, select { font: inherit; }
button, input, select, summary { min-height: 44px; }
button { cursor: pointer; }
:focus-visible { outline: 3px solid var(--color-accent); outline-offset: 3px; }
.skip-link { position: absolute; left: 1rem; top: -4rem; z-index: 5; padding: 0.65rem 0.9rem; background: var(--color-ink); color: white; }
.skip-link:focus { top: 1rem; }
.site-header, .gallery-main, .site-footer { width: min(var(--content-width), calc(100% - 2rem)); margin-inline: auto; }
.site-header { padding: clamp(2.5rem, 8vw, 6rem) 0 var(--space-8); }
.eyebrow { margin-bottom: var(--space-2); color: var(--color-accent-strong); font-size: 0.78rem; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; }
.lede { max-width: 44rem; margin-bottom: var(--space-4); color: var(--color-muted); font-size: 1.15rem; }
.rights-notice { max-width: 56rem; padding: var(--space-3) var(--space-4); border: 1px solid var(--color-border); background: var(--color-surface); color: var(--color-muted); }
.coverage-summary { display: flex; flex-wrap: wrap; gap: 1px; margin-top: var(--space-8); border: 1px solid var(--color-border); background: var(--color-border); }
.coverage-summary div { flex: 1 1 10rem; padding: var(--space-4); background: var(--color-surface); }
.coverage-summary strong { display: block; font-family: Georgia, "Times New Roman", serif; font-size: 1.8rem; font-weight: 400; }
.coverage-summary span { color: var(--color-muted); font-size: 0.9rem; }
.toolbar, .results { padding: var(--space-8) 0; border-top: 1px solid var(--color-border); }
.section-heading, .results-heading { display: flex; justify-content: space-between; gap: var(--space-4); align-items: end; }
.filter-grid { display: grid; grid-template-columns: minmax(14rem, 2fr) repeat(4, minmax(9rem, 1fr)) auto; gap: var(--space-3); align-items: end; }
.filter-control { display: grid; gap: var(--space-1); color: var(--color-muted); font-size: 0.85rem; font-weight: 700; }
input, select { width: 100%; border: 1px solid var(--color-border); border-radius: 0.4rem; padding: 0.6rem 0.75rem; background: var(--color-surface); color: var(--color-ink); }
.button { border: 1px solid var(--color-accent-strong); border-radius: 0.4rem; padding: 0.6rem 0.85rem; background: var(--color-accent); color: white; font-weight: 700; }
.button:hover { background: var(--color-accent-strong); }
.button--secondary { background: transparent; color: var(--color-accent-strong); }
.button--secondary:hover { background: var(--color-surface); }
.result-status { margin-bottom: var(--space-2); color: var(--color-muted); }
.logo-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: var(--space-4); }
.logo-card { display: flex; min-width: 0; flex-direction: column; border: 1px solid var(--color-border); background: var(--color-surface); }
.logo-card:hover, .logo-card:focus-within { border-color: var(--color-accent); }
.logo-preview { display: grid; min-height: 10rem; place-items: center; padding: var(--space-6); border-bottom: 1px solid var(--color-border); background: #f0ede7; }
.logo-preview img { display: block; max-width: 100%; max-height: 8rem; object-fit: contain; }
.preview-fallback { color: var(--color-muted); font-family: Georgia, "Times New Roman", serif; font-size: 1.1rem; text-align: center; }
.logo-card__body { display: grid; gap: var(--space-3); padding: var(--space-4); }
.logo-card__name { overflow-wrap: anywhere; }
.logo-card__legal { margin: calc(var(--space-2) * -1) 0 0; color: var(--color-muted); font-size: 0.9rem; overflow-wrap: anywhere; }
.metadata { display: flex; flex-wrap: wrap; gap: var(--space-2); margin: 0; color: var(--color-muted); font-size: 0.88rem; }
.metadata span { border: 1px solid var(--color-border); padding: 0.2rem 0.45rem; }
.rights-badge { width: fit-content; border: 1px solid var(--color-accent); padding: 0.25rem 0.5rem; color: var(--color-accent-strong); font-size: 0.8rem; font-weight: 700; }
details { border-top: 1px solid var(--color-border); padding-top: var(--space-3); }
summary { display: flex; align-items: center; cursor: pointer; color: var(--color-accent-strong); font-weight: 700; }
.details-list { display: grid; gap: var(--space-2); margin: var(--space-3) 0 0; }
.details-list dt { color: var(--color-muted); font-size: 0.8rem; font-weight: 700; }
.details-list dd { margin: 0; overflow-wrap: anywhere; }
.state { margin: var(--space-4) 0; border: 1px solid var(--color-border); padding: var(--space-6); background: var(--color-surface); }
.state--warning { background: var(--color-warning-surface); }
.state--error { background: var(--color-error-surface); }
.state p:last-child { margin-bottom: 0; }
.loading-card { min-height: 19rem; border: 1px solid var(--color-border); background: #eeeae2; animation: loading 1.5s ease-in-out infinite alternate; }
.site-footer { padding: var(--space-8) 0 var(--space-12); color: var(--color-muted); font-size: 0.9rem; }
@keyframes loading { from { opacity: 0.6; } to { opacity: 1; } }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { scroll-behavior: auto !important; animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; } }
@media (max-width: 1099px) { .filter-grid { grid-template-columns: repeat(3, minmax(10rem, 1fr)); } .filter-control--search { grid-column: 1 / -1; } }
@media (max-width: 767px) { .site-header, .gallery-main, .site-footer { width: min(100% - 1.25rem, var(--content-width)); } .section-heading, .results-heading { display: block; } .result-status { margin-top: var(--space-4); } .filter-grid { grid-template-columns: 1fr; } .filter-control--search { grid-column: auto; } .coverage-summary div { flex-basis: calc(50% - 1px); } .logo-grid { grid-template-columns: 1fr; } }
```

The loading opacity transition above is the only motion and must be disabled by the reduced-motion rule. It is a neutral placeholder, not decorative branding.

- [ ] **Step 3: Run the contract tests and verify only app-specific behavior is still missing**

Run: `pytest tests/test_gallery.py -q`

Expected: the shell assertions pass after the HTML and CSS exist; the script assertions still fail until `web/app.js` is added.

- [ ] **Step 4: Commit the shell and visual system**

```bash
git add web/index.html web/styles.css
git commit -m "feat: add logo gallery shell"
```

## Task 3: Implement registry loading, joins, coverage, and safe URLs

**Files:**
- Create: `web/app.js`

**Interfaces:**
- `loadRegistry()` returns a validated registry object or throws a user-facing error.
- `buildCards(registry)` returns sorted asset view models with `owner`, `source`, `assetUrl`, and metadata fields.
- `safeAssetUrl(stagingPath)` returns a relative local URL or `null` for unsafe paths.
- `safeSourceUrl(sourceUri)` returns an HTTP/HTTPS URL string or `null`.

- [ ] **Step 1: Add the loading and validation functions**

Implement these exact contracts before rendering:

```javascript
const REGISTRY_URL = "../data/registry-with-logos.json";
const LOCAL_ASSET_ROOT = "../data/assets/";
const REQUIRED_ARRAYS = ["institutions", "brands", "assets", "sources"];

function safeSourceUrl(value) {
  if (typeof value !== "string" || value.trim() === "") return null;
  try {
    const url = new URL(value.trim());
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

function safeAssetUrl(stagingPath) {
  if (typeof stagingPath !== "string" || stagingPath.trim() === "") return null;
  const normalized = stagingPath.trim().replaceAll("\\", "/");
  const parts = normalized.split("/");
  if (normalized.startsWith("/") || parts.includes("..") || parts.some((part) => part === "")) return null;
  return `${LOCAL_ASSET_ROOT}${parts.map(encodeURIComponent).join("/")}`;
}

function validateRegistry(value) {
  if (!value || typeof value !== "object") throw new Error("Registry data is not an object");
  for (const key of REQUIRED_ARRAYS) {
    if (!Array.isArray(value[key])) throw new Error(`Registry field ${key} is missing`);
  }
  return value;
}

async function loadRegistry() {
  if (window.location.protocol === "file:") {
    throw new Error("Serve the repository with python3 -m http.server 8000 before opening the gallery");
  }
  const response = await fetch(REGISTRY_URL, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`Registry request failed with HTTP ${response.status}`);
  return validateRegistry(await response.json());
}
```

- [ ] **Step 2: Add owner/source lookup and asset view-model construction**

Use `owner_id` as the only join key. Unknown owners remain visible as fallback cards. Use institution `short_name` then `legal_name`, and brand `display_name`. Keep the exact raw rights value and source URI in the view model.

```javascript
function displayOwnerName(entity, kind) {
  if (!entity) return "Unknown owner";
  if (kind === "institution") return entity.short_name || entity.legal_name || entity.id;
  return entity.display_name || entity.id;
}

function createOwnerMap(registry) {
  const owners = new Map();
  for (const institution of registry.institutions) owners.set(institution.id, { entity: institution, kind: "institution" });
  for (const brand of registry.brands) owners.set(brand.id, { entity: brand, kind: "brand" });
  return owners;
}

function createSourceMap(registry) {
  return new Map(registry.sources.map((source) => [source.id, source]));
}

function buildCards(registry) {
  const owners = createOwnerMap(registry);
  const sources = createSourceMap(registry);
  return registry.assets.map((asset) => {
    const owner = owners.get(asset.owner_id);
    const source = sources.get(asset.source_id);
    const entity = owner?.entity;
    const countries = owner?.kind === "brand" ? entity.country_codes || [] : entity ? [entity.country_code, ...(entity.jurisdictions || [])] : [];
    return {
      asset,
      ownerId: asset.owner_id || "unknown-owner",
      ownerKnown: Boolean(owner),
      kind: owner?.kind || "unknown",
      name: displayOwnerName(entity, owner?.kind),
      legalName: owner?.kind === "institution" && entity.legal_name !== entity.short_name ? entity.legal_name : "",
      countries: [...new Set(countries.filter(Boolean))].sort(),
      sourcePublisher: source?.publisher || "Recorded source",
      sourceUrl: safeSourceUrl(asset.source_uri),
      assetUrl: safeAssetUrl(asset.staging_path),
      rightsStatus: asset.rights_status || "unknown",
      format: asset.format || "unknown",
      variant: asset.variant || "primary",
    };
  }).sort((left, right) => [left.name, left.variant, left.format, left.asset.id].map((value) => value.toLocaleLowerCase()).join("\u0000").localeCompare(
    [right.name, right.variant, right.format, right.asset.id].map((value) => value.toLocaleLowerCase()).join("\u0000"),
  ));
}
```

- [ ] **Step 3: Add coverage and filter-option derivation**

Compute counts from loaded data. Unique asset owners count only known institution/brand IDs; missing owners are reported through the partial warning instead of inflating coverage.

```javascript
function deriveCoverage(registry, cards) {
  const totalEntities = registry.institutions.length + registry.brands.length;
  const knownOwners = new Set(cards.filter((card) => card.ownerKnown).map((card) => card.ownerId));
  return {
    totalEntities,
    assetCount: registry.assets.length,
    ownerCount: knownOwners.size,
    missingCount: Math.max(totalEntities - knownOwners.size, 0),
    unknownOwnerCount: cards.filter((card) => !card.ownerKnown).length,
  };
}

function deriveOptions(cards) {
  return {
    countries: [...new Set(cards.flatMap((card) => card.countries))].sort(),
    rights: [...new Set(cards.map((card) => card.rightsStatus))].sort(),
  };
}
```

- [ ] **Step 4: Run the contract tests and commit the data layer**

Run: `pytest tests/test_gallery.py -q`

Expected: PASS for file existence, registry path resolution, safe URL guards, and rights copy.

```bash
git add web/app.js
git commit -m "feat: load and join logo registry data"
```

## Task 4: Implement filtering, card rendering, and all user-visible states

**Files:**
- Modify: `web/index.html` only if a state hook needs a small semantic correction.
- Modify: `web/app.js`
- Modify: `web/styles.css` for card/fallback details that are not covered by Task 2.

**Interfaces:**
- `applyFilters(cards, filters)` returns the visible cards.
- `renderCards(cards)` updates `#logo-grid` using only DOM APIs.
- `renderState(name, detail)` updates loading, success, empty, partial, or fatal state regions.

- [ ] **Step 1: Add filter state and human-readable labels**

Use this filter shape and label mapping:

```javascript
const state = {
  cards: [],
  filters: { search: "", kind: "all", country: "all", format: "all", rights: "all" },
};

const rightsLabels = {
  nominative_use: "Nominative use",
  source_link_only: "Source link only",
  redistributable: "Redistributable",
  licensed: "Licensed",
  unknown: "Unknown rights",
  removed: "Removed",
};

function labelRightsStatus(value) {
  return rightsLabels[value] || `Unrecognized: ${value}`;
}

function applyFilters(cards, filters) {
  const query = filters.search.trim().toLocaleLowerCase();
  return cards.filter((card) => {
    const searchText = [card.name, card.legalName, ...card.countries].join(" ").toLocaleLowerCase();
    return (!query || searchText.includes(query))
      && (filters.kind === "all" || card.kind === filters.kind)
      && (filters.country === "all" || card.countries.includes(filters.country))
      && (filters.format === "all" || card.format === filters.format)
      && (filters.rights === "all" || card.rightsStatus === filters.rights);
  });
}
```

- [ ] **Step 2: Render each card with safe DOM APIs and explicit metadata**

Build elements with `document.createElement`, assign registry values through `textContent`, and add a `details` disclosure with exact rights/provenance values. Set `alt` to `${card.name} logo`. Use a preview fallback when `card.assetUrl` is null or the image emits `error`.

Required card content, in order:

1. Preview region with image or `Preview unavailable`.
2. Owner name and optional institution legal name.
3. Text badges for entity type, country/`Global/unknown`, format, and variant.
4. Human-readable rights badge with the raw rights status inside the disclosure.
5. `details` disclosure containing asset ID, SHA-256, source publisher, attribution, rights note, and a source link only when `safeSourceUrl` returned a value.

The source link must use:

```javascript
link.target = "_blank";
link.rel = "noopener noreferrer";
```

Never use `element.innerHTML`, `insertAdjacentHTML`, or string-built markup for registry data.

- [ ] **Step 3: Add coverage, filters, and state wiring**

On successful load:

1. Populate coverage values and show `#coverage-summary`.
2. Populate country and rights selects from `deriveOptions(cards)` while preserving the fixed `all` option.
3. Hide loading, fatal, and empty regions; show `#logo-grid`.
4. Render all cards, then announce `Showing N of M logo assets` in `#result-status`.
5. Attach `input`/`change` listeners to update `state.filters`, rerun `applyFilters`, rerender, and use `Reset filters` when no cards match.

The reset action must clear the search input and restore all selects to `all`. The result status must remain the only live region that changes on ordinary filtering so keyboard and screen-reader users are not interrupted by focus changes.

- [ ] **Step 4: Implement loading, partial, fatal, and missing-preview behavior**

Use these exact user-facing behaviors:

- Loading: leave title and rights notice visible, keep six placeholders, disable controls, and announce `Loading logo registry`.
- `file://` or fetch failure: hide the grid, show an alert panel containing `Gallery needs a local HTTP server`, the exact command `python3 -m http.server 8000`, and a `Retry` button. Do not autofocus the alert on every retry.
- Malformed registry: show `The registry data could not be read` and do not render partial counts.
- Missing owner or binary: keep the card, show a neutral fallback, preserve asset ID/rights/source metadata, and show a single partial warning with the number of affected cards.
- Filtered empty: show `No logo assets match these filters`, a short context sentence, and a visible `Reset filters` button.
- Missing source URI: show `Source not recorded` as plain text with no link.

- [ ] **Step 5: Add a manual smoke checklist and run static tests**

Run: `pytest tests/test_gallery.py -q`

Expected: PASS.

Manual smoke test:

```bash
python3 -m http.server 8000
```

Open `http://localhost:8000/web/` and verify:

- all current asset cards render, including SVG, PNG, and JPEG previews;
- the coverage line reports the current registry's entity, asset, owner, and without-logo counts;
- search, type, country, format, rights, and reset controls update the result count;
- rights details preserve the exact raw status and source metadata;
- source links open in a new tab and local previews make no network request;
- a deliberately invalid filter produces the empty state;
- keyboard tab order reaches skip link, search, filters, reset, cards, disclosures, and source links;
- narrow viewport behavior matches the 320-767px specification.

- [ ] **Step 6: Commit the interactive gallery**

```bash
git add web/index.html web/app.js web/styles.css
git commit -m "feat: render searchable logo gallery"
```

## Task 5: Document usage and add regression verification

**Files:**
- Modify: `README.md`
- Modify: `tests/test_gallery.py` only if a documentation contract assertion is needed.

**Interfaces:**
- README becomes the entry point for maintainers who want to inspect the gallery.
- Existing package validation and release commands remain unchanged.

- [ ] **Step 1: Add the gallery section after local development**

Add this section to `README.md`:

```markdown
## Local logo gallery

The repository includes a read-only browser gallery for the reviewed logo assets in
`data/registry-with-logos.json`. It shows each committed asset, including multiple
variants, with its owner, format, provenance, and rights note. The registry contains
thousands of entities but only a subset with logo assets; the gallery derives and
reports the current counts and does not render thousands of empty cards.

The gallery is not a logo-discovery or approval tool. It does not grant a licence:
trademarks remain the property of their owners, and the current assets are displayed
for identification under the per-asset rights decisions recorded in the registry.

Serve the repository root over HTTP because browsers restrict `fetch()` from a
`file://` page:

```bash
python3 -m http.server 8000
```

Open <http://localhost:8000/web/>.
```

- [ ] **Step 2: Run the complete verification suite**

Run:

```bash
pytest -q
pytest --cov=financial_registry --cov-report=term-missing --cov-fail-under=85 -q
ruff check src tests
financial-registry validate data/registry-with-logos.json
git diff --check
```

Expected: all existing tests pass, coverage remains at least 85%, Ruff reports no issues, registry validation reports `valid`, and `git diff --check` is clean.

- [ ] **Step 3: Commit documentation and final checks**

```bash
git add README.md tests/test_gallery.py
git commit -m "docs: document local logo gallery"
```

## Plan self-review

### Spec coverage

- Information hierarchy: Task 2 shell and Task 4 state wiring.
- Registry source of truth, one-card-per-asset, joins, deterministic sorting, and local paths: Task 3.
- Search and all filters: Task 4.
- Rights/provenance and safe external links: Tasks 3 and 4.
- Loading, success, empty, fatal, partial, missing-binary, and missing-source states: Task 4.
- Editorial visual tokens, typography, contrast, responsive breakpoints, focus states, and reduced motion: Task 2.
- Structural/data tests, browser smoke test, README, and existing regression suite: Tasks 1 and 5.

### Dependency order

1. Task 1 creates failing tests.
2. Task 2 creates the shell and visual contract.
3. Task 3 supplies data and view models.
4. Task 4 connects interaction and resilience behavior.
5. Task 5 documents and verifies the complete feature.

### No-placeholder check

All tasks name exact files, commands, user-facing copy, function contracts, and expected outcomes. No implementation step relies on a TBD, an unspecified edge-case instruction, or a reference to an undefined neighboring function.
