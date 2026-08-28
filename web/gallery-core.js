export const REQUIRED_ARRAYS = ["institutions", "brands", "assets", "sources"];
export const DEFAULT_PAGE_SIZE = 100;

export const rightsLabels = {
  nominative_use: "Nominative use",
  source_link_only: "Source link only",
  redistributable: "Redistributable",
  licensed: "Licensed",
  unknown: "Unknown rights",
  removed: "Removed",
};

export function text(value, fallback = "") {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

export function safeSourceUrl(value) {
  if (typeof value !== "string" || value.trim() === "") return null;
  try {
    const url = new URL(value.trim());
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

export function safeAssetUrl(stagingPath) {
  if (typeof stagingPath !== "string" || stagingPath.trim() === "") return null;
  const normalized = stagingPath.trim().replaceAll("\\", "/");
  const parts = normalized.split("/");
  if (normalized.startsWith("/") || parts.includes("..") || parts.some((part) => part === "")) return null;
  return `../data/assets/${parts.map(encodeURIComponent).join("/")}`;
}

export function validateRegistry(value) {
  if (!value || typeof value !== "object") throw new Error("Registry data is not an object");
  for (const key of REQUIRED_ARRAYS) {
    if (!Array.isArray(value[key])) throw new Error(`Registry field ${key} is missing`);
  }
  return value;
}

function displayOwnerName(entity, kind) {
  if (!entity) return "Unknown owner";
  if (kind === "institution") return text(entity.short_name, text(entity.legal_name, text(entity.id, "Unknown institution")));
  return text(entity.display_name, text(entity.id, "Unknown brand"));
}

function createOwnerMap(registry) {
  const owners = new Map();
  for (const institution of registry.institutions) {
    if (institution && typeof institution === "object" && text(institution.id)) {
      owners.set(institution.id, { entity: institution, kind: "institution" });
    }
  }
  for (const brand of registry.brands) {
    if (brand && typeof brand === "object" && text(brand.id)) {
      owners.set(brand.id, { entity: brand, kind: "brand" });
    }
  }
  return owners;
}

function createSourceMap(registry) {
  const sources = new Map();
  for (const source of registry.sources) {
    if (source && typeof source === "object" && text(source.id)) sources.set(source.id, source);
  }
  return sources;
}

function ownerCountries(owner) {
  if (!owner) return [];
  const rawCountries = owner.kind === "brand"
    ? (Array.isArray(owner.entity.country_codes) ? owner.entity.country_codes : [])
    : [owner.entity.country_code, ...(Array.isArray(owner.entity.jurisdictions) ? owner.entity.jurisdictions : [])];
  return [...new Set(rawCountries.filter((value) => typeof value === "string" && value.trim()).map((value) => value.trim().toUpperCase()))].sort();
}

export function buildCards(registry) {
  const owners = createOwnerMap(registry);
  const sources = createSourceMap(registry);
  return registry.assets.map((assetValue) => {
    const asset = assetValue && typeof assetValue === "object" ? assetValue : {};
    const ownerId = text(asset.owner_id, "unknown-owner");
    const owner = owners.get(ownerId);
    const entity = owner?.entity;
    const kind = owner?.kind || "unknown";
    const legalName = kind === "institution" && text(entity.legal_name) && entity.legal_name !== entity.short_name ? entity.legal_name : "";
    const source = sources.get(text(asset.source_id));
    const card = {
      asset,
      assetId: text(asset.id, "unknown-asset"),
      ownerId,
      ownerKnown: Boolean(owner),
      kind,
      name: displayOwnerName(entity, kind),
      legalName,
      countries: ownerCountries(owner),
      sourcePublisher: text(source?.publisher, "Recorded source"),
      sourceUrl: safeSourceUrl(asset.source_uri),
      licenseUrl: safeSourceUrl(asset.license_url),
      assetUrl: safeAssetUrl(asset.staging_path),
      rightsStatus: text(asset.rights_status, "unknown"),
      format: text(asset.format, "unknown").toLowerCase(),
      variant: text(asset.variant, "primary"),
    };
    card.searchText = [card.name, card.legalName, ...card.countries].join(" ").toLowerCase();
    return card;
  }).sort((left, right) => {
    const leftKey = [left.name, left.variant, left.format, left.assetId].map((value) => value.toLowerCase()).join("\u0000");
    const rightKey = [right.name, right.variant, right.format, right.assetId].map((value) => value.toLowerCase()).join("\u0000");
    return leftKey < rightKey ? -1 : leftKey > rightKey ? 1 : 0;
  });
}

export function limitCards(cards, limit = DEFAULT_PAGE_SIZE) {
  const normalizedLimit = Number.isFinite(limit) ? Math.max(0, Math.floor(limit)) : DEFAULT_PAGE_SIZE;
  return cards.slice(0, normalizedLimit);
}

export function recordPreviewFailure(failedAssetIds, assetId) {
  if (failedAssetIds.has(assetId)) return false;
  failedAssetIds.add(assetId);
  return true;
}

export function deriveCoverage(registry, cards) {
  const totalEntities = Number.isInteger(registry.coverage?.total_entities)
    ? registry.coverage.total_entities
    : registry.institutions.length + registry.brands.length;
  const knownOwners = new Set(cards.filter((card) => card.ownerKnown).map((card) => card.ownerId));
  return {
    totalEntities,
    assetCount: registry.assets.length,
    ownerCount: knownOwners.size,
    missingCount: Math.max(totalEntities - knownOwners.size, 0),
  };
}

export function deriveOptions(cards) {
  return {
    countries: [...new Set(cards.flatMap((card) => card.countries))].sort(),
    rights: [...new Set(cards.map((card) => card.rightsStatus))].sort(),
  };
}

export function labelRightsStatus(value) {
  return rightsLabels[value] || `Unrecognized: ${value}`;
}

export function applyFilters(cards, filters) {
  const query = filters.search.trim().toLowerCase();
  return cards.filter((card) => {
    const searchText = card.searchText || [card.name, card.legalName, ...card.countries].join(" ").toLowerCase();
    return (!query || searchText.includes(query))
      && (filters.kind === "all" || card.kind === filters.kind)
      && (filters.country === "all" || card.countries.includes(filters.country))
      && (filters.format === "all" || card.format === filters.format)
      && (filters.rights === "all" || card.rightsStatus === filters.rights);
  });
}

export function countPartialIssues(cards) {
  return cards.filter((card) => !card.ownerKnown || !card.assetUrl).length;
}
