import test from "node:test";
import assert from "node:assert/strict";

import {
  applyFilters,
  buildCards,
  countPartialIssues,
  deriveCoverage,
  labelRightsStatus,
  limitCards,
  recordPreviewFailure,
  validateRegistry,
} from "./gallery-core.js";

function sampleRegistry() {
  return {
    institutions: [
      {
        id: "inst-acme",
        short_name: "Acme Bank",
        legal_name: "Acme Bank plc",
        country_code: "us",
        jurisdictions: ["gb"],
      },
    ],
    brands: [
      { id: "brand-acme-pay", display_name: "Acme Pay", country_codes: ["ng"] },
    ],
    sources: [{ id: "src-official", publisher: "Official source" }],
    assets: [
      {
        id: "asset-institution",
        owner_id: "inst-acme",
        source_id: "src-official",
        staging_path: "logos/acme.svg",
        source_uri: "https://example.test/acme.svg",
        license_url: "javascript:alert(1)",
        rights_status: "nominative_use",
        format: "svg",
        variant: "mark",
      },
      {
        id: "asset-brand",
        owner_id: "brand-acme-pay",
        source_id: "missing-source",
        staging_path: "logos/acme-pay.png",
        source_uri: "https://example.test/acme-pay.png",
        rights_status: "redistributable",
        format: "png",
        variant: "primary",
      },
      {
        id: "asset-partial",
        owner_id: "missing-owner",
        source_id: "src-official",
        staging_path: "../outside.svg",
        source_uri: "not-a-url",
        rights_status: "unknown",
        format: "svg",
        variant: "primary",
      },
    ],
  };
}

test("validateRegistry rejects malformed registry payloads", () => {
  assert.throws(() => validateRegistry({ assets: [] }), /Registry field institutions is missing/);
});

test("buildCards resolves institutions, brands, and partial metadata safely", () => {
  const cards = buildCards(sampleRegistry());
  const institution = cards.find((card) => card.assetId === "asset-institution");
  const brand = cards.find((card) => card.assetId === "asset-brand");
  const partial = cards.find((card) => card.assetId === "asset-partial");

  assert.equal(institution.name, "Acme Bank");
  assert.equal(institution.kind, "institution");
  assert.deepEqual(institution.countries, ["GB", "US"]);
  assert.equal(institution.sourcePublisher, "Official source");
  assert.equal(institution.licenseUrl, null);

  assert.equal(brand.name, "Acme Pay");
  assert.equal(brand.kind, "brand");
  assert.deepEqual(brand.countries, ["NG"]);
  assert.equal(brand.sourcePublisher, "Recorded source");

  assert.equal(partial.ownerKnown, false);
  assert.equal(partial.assetUrl, null);
  assert.equal(partial.sourceUrl, null);
  assert.equal(partial.sourcePublisher, "Official source");
});

test("buildCards uses deterministic code-point ordering instead of host locale", () => {
  const registry = sampleRegistry();
  registry.institutions[0].short_name = "Å Bank";
  registry.brands[0].display_name = "Z Pay";

  const cards = buildCards(registry).filter((card) => card.assetId !== "asset-partial");

  assert.deepEqual(cards.map((card) => card.assetId), ["asset-brand", "asset-institution"]);
});

test("applyFilters supports search plus kind, country, format, and rights", () => {
  const cards = buildCards(sampleRegistry());

  assert.deepEqual(
    applyFilters(cards, {
      search: "acme",
      kind: "brand",
      country: "NG",
      format: "png",
      rights: "redistributable",
    }).map((card) => card.assetId),
    ["asset-brand"],
  );
  assert.deepEqual(
    applyFilters(cards, {
      search: "gb",
      kind: "all",
      country: "GB",
      format: "all",
      rights: "all",
    }).map((card) => card.assetId),
    ["asset-institution"],
  );
});

test("coverage and partial warnings account for missing owners and binaries", () => {
  const registry = sampleRegistry();
  const cards = buildCards(registry);

  assert.deepEqual(deriveCoverage(registry, cards), {
    totalEntities: 2,
    assetCount: 3,
    ownerCount: 2,
    missingCount: 0,
  });
  assert.equal(countPartialIssues(cards), 1);
});

test("coverage uses the full registry count supplied by a gallery projection", () => {
  const registry = sampleRegistry();
  registry.coverage = { total_entities: 3023 };
  const cards = buildCards(registry);

  assert.equal(deriveCoverage(registry, cards).totalEntities, 3023);
  assert.equal(deriveCoverage(registry, cards).missingCount, 3021);
});

test("recordPreviewFailure counts each asset only once across rerenders", () => {
  const failedAssetIds = new Set();

  assert.equal(recordPreviewFailure(failedAssetIds, "asset-broken"), true);
  assert.equal(recordPreviewFailure(failedAssetIds, "asset-broken"), false);
  assert.equal(recordPreviewFailure(failedAssetIds, "asset-other"), true);
  assert.deepEqual([...failedAssetIds], ["asset-broken", "asset-other"]);
});

test("limitCards bounds the rendered page while preserving source order", () => {
  const cards = Array.from({ length: 3 }, (_, index) => ({ assetId: `asset-${index}` }));

  assert.deepEqual(limitCards(cards, 2), cards.slice(0, 2));
  assert.deepEqual(limitCards(cards, 0), []);
  assert.deepEqual(limitCards(cards, 10), cards);
});

test("rights status labels remain explicit for known and unknown values", () => {
  assert.equal(labelRightsStatus("nominative_use"), "Nominative use");
  assert.equal(labelRightsStatus("future_status"), "Unrecognized: future_status");
});
