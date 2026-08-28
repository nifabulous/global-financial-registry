# Bank Logo Gallery Design

**Date:** 2026-08-27
**Status:** Design reviewed and amended; implementation plan pending review

## Summary

Add a small, dependency-free browser gallery to the repository so maintainers can inspect the logo assets currently present in the global financial registry. The gallery is a local development tool, not a new publication format or public catalog.

The page will load the existing `data/registry-with-logos.json` at runtime, join each asset to its institution or brand owner, and render the local binary from `data/assets/logos`. It will not duplicate registry records or hardcode logo metadata.

## Goals

1. Make every committed logo asset visually inspectable in a browser.
2. Preserve the registry as the single source of truth for names, ownership, provenance, format, and rights metadata.
3. Make it obvious that the registry contains thousands of entities but only a subset with logo assets; the page must not imply that every institution has a logo. All counts must be derived from the loaded registry because enrichment is ongoing.
4. Support quick visual triage through search and lightweight filters.
5. Keep the first version easy to run and maintain with no frontend framework, bundler, backend, CDN, or third-party runtime dependency.
6. Present rights and provenance accurately without granting or implying an open licence.

## Non-goals

- Downloading or discovering new logos from the browser.
- Editing registry data, approving assets, or changing rights decisions.
- Building an API, authentication layer, database, CDN, or deployment pipeline.
- Rendering all logo-less institutions as thousands of empty cards.
- Making legal determinations beyond displaying the rights and provenance already recorded in the registry.

## Source data and asset resolution

The page will fetch `../data/registry-with-logos.json` relative to `web/index.html`.

The gallery will construct its cards from the registry's `assets` array. For each asset:

1. Look up `asset.owner_id` in the `institutions` and `brands` arrays.
2. Use `short_name` when present for an institution, otherwise `legal_name`; use `display_name` for a brand.
3. Build the local image URL from `asset.staging_path`, which is rooted at `data/assets` in the repository. For example, `logos/asset_abc.svg` becomes `../data/assets/logos/asset_abc.svg`.
4. Keep one card per asset so multiple variants for one owner remain visible.
5. Use deterministic ordering: owner display name (case-insensitive), then variant, format, and asset ID.

No logo URL will be fetched from a third-party CDN. The recorded `source_uri` is displayed as provenance and linked for optional user inspection only.

## Coverage and metadata presentation

The header will calculate and display counts from the loaded data rather than embedding today's numbers:

- total entities (`institutions` plus `brands`)
- logo assets
- unique entities with at least one asset
- entities without an asset

Each card will display:

- logo preview with descriptive `alt` text
- owner name and, for institutions, the legal name where it differs
- entity type: institution or brand
- country code when available, otherwise `Global/unknown`
- asset format and variant
- rights status
- source publisher and a source link
- attribution and rights note in a compact details area

A page-level notice will state that trademarks remain the property of their respective owners, that the current assets are displayed for identification, and that no blanket open copyright licence is asserted. The notice will link to the relevant source or rights information when available.

The page-level notice will link to the repository's licensing section for the general policy. Each card will link to its own recorded source and will expose its asset-specific rights note; the page must not imply that one source's terms apply to every asset.

## User interface

`web/index.html` will provide the semantic shell:

- page title and short explanation
- coverage summary region
- filter controls with visible labels
- loading, error, and empty-results status regions
- logo grid container

`web/app.js` will:

- fetch and validate the expected registry shape
- normalize institution and brand owners into a lookup map
- derive card view models and coverage counts
- render cards and update the result count when filters change
- provide a reset-filters action
- show a useful error if the page is opened with `file://` or the registry cannot be fetched
- replace a failed image with a clearly labelled fallback rather than leaving a broken-image icon

The initial controls will be:

- free-text search across owner name, legal name, and country code
- entity type: all, institution, or brand
- country code, populated from available institution/brand data
- format: all, SVG, PNG, JPEG, or WEBP
- rights status
- reset filters

`web/styles.css` will define a responsive card grid, restrained visual treatment, readable metadata, visible keyboard focus states, and a compact mobile layout. Logo previews will use a fixed-height containment box so different aspect ratios do not distort the grid.

## Accessibility and resilience

- Use semantic headings, landmarks, labels, buttons, and lists.
- Keep filter changes and result counts available to assistive technology through an `aria-live` status.
- Provide meaningful image alt text and a text fallback when an image fails.
- Do not communicate rights or status through color alone.
- Use `loading="lazy"` and `decoding="async"` for previews.
- Handle malformed/missing owner records and missing local files without aborting the entire gallery; show an identifiable fallback card and continue rendering other assets.

## Files

- `web/index.html` — semantic document shell
- `web/app.js` — data loading, joining, filtering, and rendering
- `web/styles.css` — responsive presentation
- `tests/test_gallery.py` — structural and registry-to-local-asset checks
- `README.md` — local serving instructions and scope note

## Local usage

From the repository root:

```bash
python3 -m http.server 8000
```

Open <http://localhost:8000/web/> in a browser. The page intentionally expects HTTP serving because browser security rules prevent `fetch()` from reliably loading the registry when the HTML is opened directly from `file://`.

## Verification

Automated checks will verify that:

- the three gallery files exist and contain the expected data-loading/filtering hooks;
- every `staging_path` in the derived registry resolves to a committed local file;
- the gallery's rights disclaimer is present;
- the existing registry validation, lint, and test suite still pass.

Manual smoke verification will serve the repository locally and confirm that all current assets render, SVG/PNG/JPEG previews work, search and filters update the grid, source links open, and loading/error/empty states are understandable.

## Future extension points

The data join and rendering model leave room for a later public catalog, generated lightweight index, thumbnail pipeline, or hosted deployment. Those are deliberately deferred until the local viewer proves useful and the registry's coverage and rights workflow are broader.

## Design review addendum

This addendum folds the second design review into the implementation source of truth.

### What already exists

- `data/registry-with-logos.json` is the maintained source for the institution, brand, and reviewed-asset counts at the time the page is opened; enrichment is ongoing, so the gallery must derive counts rather than hardcode them.
- `data/assets/logos` contains the local SVG, PNG, and JPEG binaries referenced by the registry.
- The Python package already validates asset paths, formats, hashes, and rights states. The gallery must consume that output and must not reimplement those rules.
- `README.md` documents the registry and rights model but has no gallery instructions yet; the implementation will add the local server command there.
- The standalone repository has no `DESIGN.md`, shared frontend component library, or existing gallery pattern. The gallery will therefore define a small local visual vocabulary in `web/styles.css` and avoid pretending that a larger design system exists.

### Information architecture and scan order

This is an app-like inspection tool, not a marketing page. The first viewport must answer three questions in order: what is this, how much coverage exists, and how do I find a logo?

```text
Global Financial Registry
├── Purpose and rights notice
├── Coverage summary
│   ├── total entities
│   ├── logo assets
│   ├── entities with assets
│   └── entities without assets
├── Find and filter toolbar
│   ├── search
│   ├── entity type
│   ├── country
│   ├── format
│   ├── rights status
│   └── reset
├── Result status and count
└── Logo asset list
    └── one inspectable card per asset
```

The header, coverage summary, and search field are visible without scrolling on a typical laptop. The coverage summary is an inline band of values, not a decorative three-card feature grid. Cards are justified because each card is an asset the user is inspecting, not because cards are being used as page decoration.

### Interaction state table

| State | What the user sees | Primary recovery or next action |
| --- | --- | --- |
| Loading | Page title and rights notice remain visible; six neutral preview placeholders appear; filters are disabled; status reads `Loading logo registry`. | Wait. The loading state must not look like an empty registry. |
| Success | Coverage values are populated, the result count is announced, and the asset grid is rendered in deterministic order. | Search, filter, inspect a card, or open its source. |
| Filtered empty | The grid is replaced by `No logo assets match these filters`, with the active result count at zero and a visible `Reset filters` button. | Reset filters, then try a broader search. |
| Fetch error or `file://` open | A concise error panel explains that the page needs a local HTTP server, shows `python3 -m http.server 8000`, and provides a `Retry` button. | Start the server or retry after fixing the path. |
| Malformed registry | The page keeps its shell but shows `The registry data could not be read` and does not render misleading partial counts. | Retry after restoring a valid registry file. |
| Partial asset metadata | The coverage summary shows the loaded counts and a warning that some metadata is incomplete. The affected asset still gets a card with a text fallback. | Inspect the available metadata or open the recorded source. |
| Missing or failed binary | The card retains the owner name, asset ID, format, rights, and source metadata. The preview area says `Preview unavailable` instead of showing a broken-image icon. | Open the source link or repair the local binary. |
| Missing source link | The card shows `Source not recorded` as plain text and does not render a dead or unsafe link. | Use the rights note and asset ID for follow-up. |

All state text is user-facing and actionable. The result status uses `role="status"` and `aria-live="polite"`; fatal errors use an alert region without repeatedly stealing focus.

### User journey storyboard

| Moment | User action | User should feel | Design support |
| --- | --- | --- | --- |
| First 5 seconds | Lands on the page and scans the title, coverage values, and first row of previews. | Oriented and confident about what is actually covered. | Left-aligned title, short purpose sentence, inline counts, and immediate local previews. |
| First minute | Types a bank or brand name, chooses a format or country, and sees the result count change. | In control, with no puzzle to solve. | One prominent search field, visible labels, predictable select controls, and reset at hand. |
| First 5 minutes | Opens a card's rights details and source link to decide whether the asset is suitable for further review. | Informed rather than falsely reassured. | Rights badge plus full rights note, publisher, source URI, and no open-licence implication. |
| Repeated maintenance use | Returns after new assets are promoted and compares variants or missing previews. | The page feels dependable because it follows the registry automatically. | Runtime data loading, deterministic sorting, explicit partial states, and no manually duplicated card data. |

### Visual direction and AI-slop guardrails

The visual direction is an editorial catalog for technical review: quiet, left-aligned, information-dense, and built around the logos themselves. It is not a hero page, a dashboard mosaic, or a generic SaaS landing page.

Define these CSS variables in `web/styles.css`:

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
}
```

Use `Georgia, "Times New Roman", serif` for the page title and `"Avenir Next", "Trebuchet MS", sans-serif` for body and controls, with 16px minimum body text and a 1.5 line height. Do not load fonts or icons from a CDN. Use dark ink for primary text, muted ink for secondary text, and the burnt-orange accent for links, focus rings, and actions. Verify body text at a minimum 4.5:1 contrast ratio and large text at 3:1.

The page has no gradients, decorative blobs, emoji, colored icon circles, ornamental shadows, or oversized marketing copy. Cards use a thin border and a restrained radius, with a visible border change on hover and focus. The preview box has a neutral surface and `object-fit: contain`, so aspect-ratio differences do not create visual noise. Rights and entity badges use text plus a border or icon shape; color never carries their meaning alone.

Rights values are rendered as human-readable labels such as `Nominative use` or `Source link only`, while the exact registry value remains available in the disclosure text or a non-visual attribute for auditability. The UI must not silently translate an unknown value into a more permissive label.

### Responsive and accessibility specification

- At 320-767px, the page uses one column, the filter controls stack in a single readable flow, the coverage values wrap into two rows, and no control requires horizontal scrolling.
- At 768-1099px, the grid uses two columns and filters may occupy two rows while retaining their visible labels.
- At 1100px and above, the grid uses `repeat(auto-fit, minmax(240px, 1fr))` with a sensible maximum content width; it may show three or four columns depending on viewport width.
- All controls, source links, reset/retry buttons, and disclosure summaries have at least a 44px hit area. The page provides a skip link, a logical tab order, a 3px visible focus outline, and no hover-only information.
- Use landmarks (`header`, `main`, `section`, `footer`), one `h1`, nested headings for coverage and results, visible `<label>` elements, and descriptive link text. Do not use placeholder text as the only label.
- Card names and source links must remain usable for long names and narrow screens through wrapping, not clipping. Missing country, variant, and source values use explicit text such as `Global/unknown` or `Not recorded`.
- Respect `prefers-reduced-motion`; the first version has no required animation beyond an optional opacity transition that can be disabled.
- Use `textContent` and DOM APIs for registry values. Never interpolate names, rights notes, or source URLs through `innerHTML`. Only render external links when the parsed URL is HTTP or HTTPS, and set `target="_blank" rel="noopener noreferrer"` for those links.

### Resolved design decisions

| Decision | Resolution | Reason |
| --- | --- | --- |
| Gallery unit | One card per asset, not one card per owner. | Multiple variants remain visible and auditable. |
| Coverage message | Show total entities, assets, unique owners, and entities without assets. | Prevents the page from implying global logo completeness. |
| Brand geography | Use `Global/unknown` when a brand has no country code. | Avoids inventing a country for a global brand. |
| Rights detail | Show status in the card and the full note inside a collapsed disclosure. | Keeps scanning fast while preserving the legal/provenance context. |
| Sorting | Owner name, variant, format, then asset ID, case-insensitive. | Stable ordering makes visual comparisons and test failures reproducible. |
| Missing owner | Render a fallback owner label and asset ID, keep the card, and mark metadata incomplete. | One bad record must not hide otherwise valid logos. |
| External navigation | Source links open a new tab with `noopener noreferrer`; local assets never fetch remotely. | Preserves the local-only viewer while making provenance inspectable. |
| Empty results | Reset filters is the primary action. | It is the only recovery action the page can perform without changing registry data. |

### Explicitly not in scope

- Hosted deployment, custom domain, GitHub Pages, or a public API. These require a separate review of caching, URL stability, and legal presentation.
- User-submitted corrections, asset approval, download buttons, or bulk export. The gallery is read-only and must not bypass the curated promotion workflow.
- A full institution directory with one empty row per logo-less entity. The page reports the missing-logo count and renders only actual assets to keep the inspection task focused.
- A full visual design system or brand identity exercise. The local tokens are enough for this tool; a broader system should be a separate product-design task.

## Implementation tasks

Synthesized from the design review. Each task is directly traceable to a review finding.

- [ ] **T1 (P1, human: ~2h / CC: ~15min)** — Gallery shell and information hierarchy — implement the title, rights notice, inline coverage summary, filter toolbar, result status, and asset grid in the specified scan order.
  - Surfaced by: Information architecture pass.
  - Files: `web/index.html`, `web/app.js`, `web/styles.css`.
  - Verify: structural gallery tests and a local browser smoke test show the first viewport in the specified order.
- [ ] **T2 (P1, human: ~2h / CC: ~15min)** — Registry join and safe local asset resolution — derive cards from `assets`, join owners by ID, use `staging_path`, validate HTTP source URLs, and render unknown owners without aborting.
  - Surfaced by: Source-data, resilience, and security review.
  - Files: `web/app.js`, `tests/test_gallery.py`.
  - Verify: every current staging path resolves locally; malformed and missing-owner fixtures render a fallback card.
- [ ] **T3 (P1, human: ~1.5h / CC: ~10min)** — Complete interaction states — implement loading placeholders, filtered-empty reset, fetch/file-protocol error with retry and server instructions, malformed-data error, partial metadata warning, and failed-image fallback.
  - Surfaced by: Interaction state pass.
  - Files: `web/index.html`, `web/app.js`, `web/styles.css`, `tests/test_gallery.py`.
  - Verify: each state is reachable in a manual smoke test and has the specified user-facing action.
- [ ] **T4 (P2, human: ~1.5h / CC: ~10min)** — Editorial visual treatment — add the CSS tokens, typography, contrast-safe accent, border-only cards, preview containment, and no-gradient/no-decoration guardrails.
  - Surfaced by: AI-slop and visual-specificity pass.
  - Files: `web/styles.css`.
  - Verify: inspect the page at desktop and mobile widths; run a contrast check on body text and controls.
- [ ] **T5 (P1, human: ~1.5h / CC: ~10min)** — Responsive and accessible interaction — implement breakpoints, 44px targets, skip link, focus states, semantic landmarks, live result status, long-name wrapping, and reduced-motion behavior.
  - Surfaced by: Responsive and accessibility pass.
  - Files: `web/index.html`, `web/app.js`, `web/styles.css`, `tests/test_gallery.py`.
  - Verify: keyboard-only pass at desktop and mobile widths plus an automated structural accessibility assertion set.
- [ ] **T6 (P2, human: ~45min / CC: ~5min)** — Documentation and regression checks — document local serving and the current derived coverage scope, and preserve the existing registry validation, lint, and test commands.
  - Surfaced by: Existing-leverage and verification review.
  - Files: `README.md`, `tests/test_gallery.py`.
  - Verify: `pytest -q`, `ruff check src tests`, registry validation, and a local `python3 -m http.server 8000` smoke test.

## Design review completion

The initial design score was 7/10. After this addendum, the design is 8.8/10 for this deliberately small local tool. It is ready for an implementation plan, with the only deferred work being hosted/public-catalog concerns that are explicitly outside this feature.

| Pass | Initial | After review | Main change |
| --- | ---: | ---: | --- |
| Information architecture | 7 | 9 | Added scan order and page hierarchy. |
| Interaction states | 6 | 9 | Added loading, empty, error, partial, and fallback behavior. |
| User journey | 5 | 8 | Added first-visit, inspection, and repeat-maintenance storyboard. |
| AI-slop risk | 5 | 9 | Replaced vague styling with concrete editorial rules and tokens. |
| Design system alignment | 6 | 8 | Documented the absence of a shared system and defined local tokens. |
| Responsive and accessibility | 6 | 9 | Added viewport-specific layout and measurable accessibility requirements. |
| Unresolved decisions | 4 | 9 | Resolved card unit, sorting, geography, rights detail, and failure behavior. |

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | Not run; no product-direction gap surfaced. |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | Not run. |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 0 | — | Not run; should follow the implementation plan. |
| Design Review | `/plan-design-review` | UI/UX gaps | 1 | COMPLETE | 7.0/10 → 8.8/10, 0 unresolved decisions. |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | Not run. |

**VERDICT:** Design review complete for the local gallery; proceed to implementation planning. Run engineering review after the implementation plan is drafted.

NO UNRESOLVED DECISIONS
