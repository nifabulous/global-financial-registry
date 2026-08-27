const REGISTRY_URL = "../data/registry-with-logos.json";
const LOCAL_ASSET_ROOT = "../data/assets/";
const REQUIRED_ARRAYS = ["institutions", "brands", "assets", "sources"];

const rightsLabels = {
  nominative_use: "Nominative use",
  source_link_only: "Source link only",
  redistributable: "Redistributable",
  licensed: "Licensed",
  unknown: "Unknown rights",
  removed: "Removed",
};

const state = {
  cards: [],
  filters: { search: "", kind: "all", country: "all", format: "all", rights: "all" },
  partialIssueCount: 0,
};

const elements = {
  coverageSummary: document.querySelector("#coverage-summary"),
  entityCount: document.querySelector("#entity-count"),
  assetCount: document.querySelector("#asset-count"),
  ownerCount: document.querySelector("#owner-count"),
  missingCount: document.querySelector("#missing-count"),
  searchInput: document.querySelector("#search-input"),
  entityTypeFilter: document.querySelector("#entity-type-filter"),
  countryFilter: document.querySelector("#country-filter"),
  formatFilter: document.querySelector("#format-filter"),
  rightsFilter: document.querySelector("#rights-filter"),
  resetFilters: document.querySelector("#reset-filters"),
  resultStatus: document.querySelector("#result-status"),
  partialWarning: document.querySelector("#partial-warning"),
  fatalState: document.querySelector("#fatal-state"),
  emptyState: document.querySelector("#empty-state"),
  loadingState: document.querySelector("#loading-state"),
  logoGrid: document.querySelector("#logo-grid"),
};

function text(value, fallback = "") {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

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

function buildCards(registry) {
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
    return {
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
  }).sort((left, right) => {
    const leftKey = [left.name, left.variant, left.format, left.assetId].map((value) => value.toLocaleLowerCase()).join("\u0000");
    const rightKey = [right.name, right.variant, right.format, right.assetId].map((value) => value.toLocaleLowerCase()).join("\u0000");
    return leftKey.localeCompare(rightKey);
  });
}

function deriveCoverage(registry, cards) {
  const totalEntities = registry.institutions.length + registry.brands.length;
  const knownOwners = new Set(cards.filter((card) => card.ownerKnown).map((card) => card.ownerId));
  return {
    totalEntities,
    assetCount: registry.assets.length,
    ownerCount: knownOwners.size,
    missingCount: Math.max(totalEntities - knownOwners.size, 0),
  };
}

function deriveOptions(cards) {
  return {
    countries: [...new Set(cards.flatMap((card) => card.countries))].sort(),
    rights: [...new Set(cards.map((card) => card.rightsStatus))].sort(),
  };
}

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

function setHidden(element, hidden) {
  if (element) element.hidden = hidden;
}

function setControlsDisabled(disabled) {
  for (const control of [elements.searchInput, elements.entityTypeFilter, elements.countryFilter, elements.formatFilter, elements.rightsFilter, elements.resetFilters]) {
    if (control) control.disabled = disabled;
  }
}

function clearChildren(element) {
  if (!element) return;
  while (element.firstChild) element.removeChild(element.firstChild);
}

function setText(element, value) {
  if (element) element.textContent = value;
}

function formatCount(value) {
  return Number(value).toLocaleString();
}

function populateSelect(select, values, labelFor = (value) => value) {
  if (!select) return;
  while (select.options.length > 1) select.remove(1);
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = labelFor(value);
    select.append(option);
  }
}

function renderCoverage(coverage) {
  setText(elements.entityCount, formatCount(coverage.totalEntities));
  setText(elements.assetCount, formatCount(coverage.assetCount));
  setText(elements.ownerCount, formatCount(coverage.ownerCount));
  setText(elements.missingCount, formatCount(coverage.missingCount));
  setHidden(elements.coverageSummary, false);
}

function renderPartialWarning() {
  if (!elements.partialWarning) return;
  if (state.partialIssueCount === 0) {
    setHidden(elements.partialWarning, true);
    setText(elements.partialWarning, "");
    return;
  }
  setText(elements.partialWarning, `${formatCount(state.partialIssueCount)} asset preview or owner record(s) need attention. The affected cards remain visible with their recorded metadata.`);
  setHidden(elements.partialWarning, false);
}

function appendDetail(list, label, value) {
  const term = document.createElement("dt");
  term.textContent = label;
  const description = document.createElement("dd");
  description.textContent = value;
  list.append(term, description);
}

function appendLinkDetail(list, label, url, missingLabel = "Source not recorded") {
  const term = document.createElement("dt");
  term.textContent = label;
  const description = document.createElement("dd");
  if (url) {
    const link = document.createElement("a");
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = url;
    description.append(link);
  } else {
    description.textContent = missingLabel;
  }
  list.append(term, description);
}

function createPreview(card) {
  const preview = document.createElement("div");
  preview.className = "logo-preview";
  const fallback = document.createElement("span");
  fallback.className = "preview-fallback";
  fallback.textContent = "Preview unavailable";
  if (!card.assetUrl) {
    preview.append(fallback);
    return preview;
  }

  const image = document.createElement("img");
  image.src = card.assetUrl;
  image.alt = `${card.name} logo`;
  image.loading = "lazy";
  image.decoding = "async";
  image.addEventListener("error", () => {
    if (image.isConnected) image.remove();
    if (!fallback.isConnected) preview.append(fallback);
    state.partialIssueCount += 1;
    renderPartialWarning();
  }, { once: true });
  preview.append(image);
  return preview;
}

function createCard(card) {
  const article = document.createElement("article");
  article.className = "logo-card";
  article.setAttribute("role", "listitem");
  article.append(createPreview(card));

  const body = document.createElement("div");
  body.className = "logo-card__body";

  const heading = document.createElement("h3");
  heading.className = "logo-card__name";
  heading.textContent = card.name;
  body.append(heading);

  if (card.legalName) {
    const legalName = document.createElement("p");
    legalName.className = "logo-card__legal";
    legalName.textContent = card.legalName;
    body.append(legalName);
  }

  const metadata = document.createElement("p");
  metadata.className = "metadata";
  for (const value of [
    card.kind === "unknown" ? "Unknown owner" : card.kind === "institution" ? "Institution" : "Brand",
    card.countries.length ? card.countries.join(", ") : "Global/unknown",
    card.format.toUpperCase(),
    card.variant,
  ]) {
    const badge = document.createElement("span");
    badge.textContent = value;
    metadata.append(badge);
  }
  body.append(metadata);

  const rights = document.createElement("span");
  rights.className = "rights-badge";
  rights.textContent = labelRightsStatus(card.rightsStatus);
  rights.title = `Registry rights status: ${card.rightsStatus}`;
  body.append(rights);

  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = "Rights and provenance";
  details.append(summary);
  const list = document.createElement("dl");
  list.className = "details-list";
  appendDetail(list, "Asset ID", card.assetId);
  appendDetail(list, "Rights status", card.rightsStatus);
  appendDetail(list, "SHA-256", text(card.asset.sha256, "Not recorded"));
  appendDetail(list, "Source publisher", card.sourcePublisher);
  appendDetail(list, "Attribution", text(card.asset.attribution_text, "Not recorded"));
  appendDetail(list, "Rights note", text(card.asset.rights_note, "Not recorded"));
  appendLinkDetail(list, "Source", card.sourceUrl);
  if (card.licenseUrl) appendLinkDetail(list, "Licence", card.licenseUrl, "Licence not recorded");
  details.append(list);
  body.append(details);

  article.append(body);
  return article;
}

function renderCards(cards) {
  clearChildren(elements.logoGrid);
  if (cards.length === 0) {
    setHidden(elements.logoGrid, true);
    setHidden(elements.emptyState, false);
    return;
  }
  const fragment = document.createDocumentFragment();
  for (const card of cards) fragment.append(createCard(card));
  elements.logoGrid.append(fragment);
  setHidden(elements.emptyState, true);
  setHidden(elements.logoGrid, false);
}

function updateView() {
  const visibleCards = applyFilters(state.cards, state.filters);
  renderCards(visibleCards);
  setText(elements.resultStatus, `Showing ${formatCount(visibleCards.length)} of ${formatCount(state.cards.length)} logo assets`);
  renderPartialWarning();
}

function resetFilters() {
  state.filters = { search: "", kind: "all", country: "all", format: "all", rights: "all" };
  elements.searchInput.value = "";
  elements.entityTypeFilter.value = "all";
  elements.countryFilter.value = "all";
  elements.formatFilter.value = "all";
  elements.rightsFilter.value = "all";
  updateView();
}

function bindControls() {
  const updateFilters = () => {
    state.filters = {
      search: elements.searchInput.value,
      kind: elements.entityTypeFilter.value,
      country: elements.countryFilter.value,
      format: elements.formatFilter.value,
      rights: elements.rightsFilter.value,
    };
    updateView();
  };
  elements.searchInput.addEventListener("input", updateFilters);
  for (const select of [elements.entityTypeFilter, elements.countryFilter, elements.formatFilter, elements.rightsFilter]) {
    select.addEventListener("change", updateFilters);
  }
  elements.resetFilters.addEventListener("click", resetFilters);
  for (const resetButton of document.querySelectorAll("[data-reset-filters]")) resetButton.addEventListener("click", resetFilters);
}

function showFatalError(error) {
  setHidden(elements.loadingState, true);
  setHidden(elements.logoGrid, true);
  setHidden(elements.emptyState, true);
  setHidden(elements.coverageSummary, true);
  setHidden(elements.partialWarning, true);
  clearChildren(elements.fatalState);

  const heading = document.createElement("h3");
  heading.textContent = window.location.protocol === "file:" ? "Gallery needs a local HTTP server" : "The registry data could not be read";
  const message = document.createElement("p");
  message.textContent = window.location.protocol === "file:"
    ? "Browsers block the registry fetch when this page is opened directly from a file."
    : text(error?.message, "The registry request failed. Check the file and try again.");
  const command = document.createElement("code");
  command.textContent = "python3 -m http.server 8000";
  const commandLine = document.createElement("p");
  commandLine.append(command);
  const retry = document.createElement("button");
  retry.className = "button";
  retry.type = "button";
  retry.textContent = "Retry";
  retry.addEventListener("click", bootstrap, { once: true });
  elements.fatalState.append(heading, message, commandLine, retry);
  setHidden(elements.fatalState, false);
  setText(elements.resultStatus, "Logo registry unavailable");
}

async function bootstrap() {
  setControlsDisabled(true);
  setHidden(elements.loadingState, false);
  setHidden(elements.logoGrid, true);
  setHidden(elements.emptyState, true);
  setHidden(elements.fatalState, true);
  setHidden(elements.coverageSummary, true);
  try {
    const registry = await loadRegistry();
    state.cards = buildCards(registry);
    state.partialIssueCount = state.cards.filter((card) => !card.ownerKnown || !card.assetUrl).length;
    renderCoverage(deriveCoverage(registry, state.cards));
    const options = deriveOptions(state.cards);
    populateSelect(elements.countryFilter, options.countries);
    populateSelect(elements.rightsFilter, options.rights, labelRightsStatus);
    setHidden(elements.loadingState, true);
    setHidden(elements.fatalState, true);
    setHidden(elements.logoGrid, false);
    setControlsDisabled(false);
    updateView();
  } catch (error) {
    showFatalError(error);
  }
}

bindControls();
bootstrap();
