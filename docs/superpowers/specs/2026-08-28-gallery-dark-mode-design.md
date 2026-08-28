# Gallery dark mode design

**Date:** 2026-08-28
**Status:** Approved for specification review

## Goal

Give the local logo gallery an accessible, persistent theme choice without changing the gallery's data model or requiring a runtime dependency. The default follows the operating system preference; users can override it with Light or Dark.

## User experience

- Add a labeled theme selector to the gallery header with three values: `System`, `Light`, and `Dark`.
- Use `System` when there is no saved preference.
- Apply a saved Light or Dark override on the next visit; changing the selector applies the theme immediately.
- Keep the control keyboard accessible, at least 44px tall, and understandable without relying on an icon or color alone.
- Preserve all current gallery behavior, content, rights disclosures, filters, and responsive layouts.

## Theme state and data flow

1. A small `web/theme.js` module owns the supported values, normalization, system-resolution, storage, and document-attribute helpers.
2. The app reads the saved value, normalizes unknown values to `system`, and initializes the selector.
3. Selecting a value writes the normalized value to `localStorage`, updates the document theme attribute for explicit overrides, and removes the attribute for `system`.
4. CSS uses the existing custom-property palette. Light remains the default; a dark media-query palette applies when no explicit attribute is present and the system is dark. Explicit `data-theme="light"` or `data-theme="dark"` overrides the media preference.
5. A small guarded head script applies an explicit saved override before the stylesheet paints, preventing a visible light-to-dark flash. Storage failures fall back to system behavior.

The theme is presentation state only. It must never alter registry data, asset URLs, rights labels, or filtering semantics.

## Visual tokens

The dark palette will define high-contrast values for:

- canvas, surfaces, text, muted text, borders, links, and visited links;
- accent and strong accent controls; and
- warning, error, preview, and loading surfaces.

The existing spacing, typography, card layout, focus ring, and responsive breakpoints remain unchanged. `color-scheme` will be set to match the resolved palette so native form controls render appropriately.

## Testing and acceptance

- Add `web/theme.test.mjs` tests for supported-value normalization, system preference resolution, explicit attribute mapping, and storage round trips using a small fake storage object.
- Add gallery contract assertions for the theme control, early initialization hook, and stylesheet theme selectors.
- Run the existing Python suite, coverage gate, Ruff, registry/manifest validation, Node gallery tests, and new theme tests.
- Manually verify System, Light, and Dark in a local server, including reload persistence, keyboard operation, focus visibility, form-control contrast, and reduced-motion behavior.

## Boundaries

This change is limited to the local gallery UI. It does not add a framework, external package, remote asset, server endpoint, or logo-data change.
