# Bank Logo Gallery Design

**Date:** 2026-08-27  
**Status:** Design approved; implementation plan pending review

## Summary

Add a small, dependency-free browser gallery to the repository so maintainers can inspect the logo assets currently present in the global financial registry. The gallery is a local development tool, not a new publication format or public catalog.

The page will load the existing `data/registry-with-logos.json` at runtime, join each asset to its institution or brand owner, and render the local binary from `data/assets/logos`. It will not duplicate registry records or hardcode logo metadata.

## Goals

1. Make every committed logo asset visually inspectable in a browser.
2. Preserve the registry as the single source of truth for names, ownership, provenance, format, and rights metadata.
3. Make it obvious that the current registry contains 3,023 entities but only 54 logo assets belonging to 46 unique entities; the page must not imply that every institution has a logo.
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
