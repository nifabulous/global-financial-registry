# Global Financial Registry Core

Reproducible global financial institution and brand registry core.

This package is a standalone, reproducible registry that ingests normalized candidates, resolves entities deterministically, validates logo assets and rights, and emits deterministic release bundles. It is isolated from the Relay/SWIFT Routing runtime.

## Local development

```bash
cd global-financial-registry
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
python -m pytest -q
financial-registry --help
```

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

## Release contract

The release bundle is the source of truth; no mutable database is introduced. All published dates are timezone-aware UTC, release versions are SemVer 2.0.0, and JSON is deterministic (UTF-8, sorted keys, stable list ordering, trailing newline).

```bash
cd global-financial-registry
pip install -e '.[dev]'
python -m pytest -q
financial-registry validate data/fixtures/candidates.json
financial-registry release-build data/fixtures/candidates.json dist/release \
  --version 0.1.0 \
  --generated-at 2026-08-26T00:00:00+00:00 \
  --generation-commit fixture-commit
financial-registry source-pilot data/registry.json \
  --snapshot-dir data/snapshots --max-records 1000 \
  --generated-at 2026-08-27T00:00:00+00:00
financial-registry logo-discover data/fixtures/candidates.json dist/logo-candidates.json
financial-registry logo-promote data/registry.json dist/logo-candidates.json \
  data/logo-decisions.json data/registry-with-logos.json \
  --asset-root data/assets
financial-registry wikidata-suggest data/fixtures/candidates.json dist/wikidata-suggestions.json
financial-registry wikidata-logo-discover data/registry.json data/wikidata-mappings.json dist/wikidata-logo-candidates.json
```

### Guarantees

- **Source of truth:** The published release bundle (`institutions.json`, `brands.json`, `identifiers.json`, `aliases.json`, `rekey-events.json`, `relationships.json`, `assets-manifest.json`, `sources.json`, `checksums.txt`, `schema-version.json`) is the only publication output.
- **Rights gate:** Binary assets are emitted for `redistributable`, `licensed`, and explicitly reviewed `nominative_use` rights states. `source_link_only` emits metadata and a source URI without a public binary. `unknown`, `removed`, and `source_link_only` assets never emit a public binary; licensed assets require `permission_reference`, territory coverage, and a non-expired permission. Nominative-use assets require a policy note and are limited to identifying the corresponding institution without implying endorsement.
- **Source ingestion:** `GLEIFConnector` fetches a bounded, replayable slice of the public GLEIF LEI API into a content-addressed snapshot, then normalizes LEI, BIC, registration, name, and jurisdiction data into `CandidateRecord` values. Regulator-specific crawlers remain separate adapters.
- **Identity:** Every institution has a curated `canonical_key`; source identifiers are aliases and `RekeyEvent` preserves history without changing the canonical ID. Brand ownership is via sourced `Relationship(brand_of)`.
- **Provenance:** Every published record references a source and successful `SourceRun`. Source failures preserve the prior verified snapshot as warnings.
- **Determinism:** Same input and explicit `--generated-at` produce byte-identical outputs; builds are atomic via temporary directories and `checksums.txt`. `schema-version.json` describes the other files (it is excluded from its own manifest to avoid a self-hash cycle), while `checksums.txt` records its actual digest. Populated output directories are rejected; an empty caller-created directory is allowed.
- **Lifecycle:** `draft -> validated -> published -> superseded` and `published -> withdrawn` with predecessor/successor/withdrawal metadata. Only a validated bundle may be published.
- **Coverage disclaimer:** This fixture-only core makes no global coverage claim and publishes counts, unresolved matches, stale sources, and provenance gaps in `schema-version.json`. Raw snapshots are stored outside public releases.
- **Licensing:** Code is Apache-2.0; project-created normalized metadata is CC BY 4.0 (attribution required); third-party assets retain per-asset rights terms.
- **Asset formats:** SVG, PNG, WEBP, and JPEG inputs are accepted. JPEG and `.jpeg` inputs are normalized to `.jpg` output paths after metadata stripping and dimension checks.
- **Deferred:** Schedulers, metrics, object storage, API/CDN, public catalog, governance UI, SDK packages, and billing belong to later plans.

## Testing

```bash
python -m pytest -q
python -m pytest --cov=financial_registry --cov-report=term-missing -q
ruff check src tests
```

## Fixture data

`data/fixtures/candidates.json` contains two institutions (`inst_example_bank` GB and `inst_example_wallet` NG), two brands, identifiers (BIC and domain), brand_of relationships, a redistributable SVG asset (`example-bank.svg`) and a source-link-only wallet asset, source definitions, successful source runs, an alias, and a rekey event. `asset_root` is `logos` relative to the fixture directory; `FixtureConnector` resolves it to `data/fixtures/logos`.

## GLEIF data pilot

The GLEIF connector is deliberately bounded by default (`max_records=1000`) so a first run cannot accidentally request the entire multi-million-record population. Pass `max_records=None` only from a deliberate bulk-ingestion job after capacity, storage, and API-use limits have been reviewed.

```python
from financial_registry.connectors import GLEIFConnector
from financial_registry.snapshots import FilesystemSnapshotStore

connector = GLEIFConnector(
    FilesystemSnapshotStore("data/snapshots"),
    filters={"entity.status": "ACTIVE", "entity.legalAddress.country": "US"},
    max_records=1000,
)
snapshot = connector.fetch()
candidates = connector.normalize(snapshot)
print(snapshot.sha256, len(candidates))
```

Raw snapshots are replay inputs and should remain outside published release bundles. The GLEIF feed identifies legal entities; it does not by itself establish that every returned entity is a bank or provide a redistributable logo. Use regulator adapters and the logo rights-review workflow to enrich and classify the candidates.

## Regulator data pilots

`FDICConnector` reads the FDIC BankFind institution API. It defaults to `ACTIVE:1`, requests the institution identity/classification fields needed for matching, and emits FDIC ID, certificate, and LEI identifiers plus source-backed categories such as `commercial_bank`, `savings_bank`, and `foreign_branch`.

```python
from financial_registry.connectors import FDICConnector
from financial_registry.snapshots import FilesystemSnapshotStore

connector = FDICConnector(
    FilesystemSnapshotStore("data/snapshots/fdic"),
    max_records=1000,
)
snapshot = connector.fetch()
candidates = connector.normalize(snapshot)
```

`ECBConnector` discovers the current supervised-entities XLSX from the ECB banking-supervision index, snapshots the workbook, and normalizes both significant and less-significant entity sheets. Its classifications distinguish credit institutions, branches, and financial holding companies. Set `max_records=None` only for an intentional full workbook run.

Both regulator feeds are classification evidence, not logo sources. A candidate should be promoted into the curated registry only after it is matched to the GLEIF/entity backbone and its logo has passed the rights workflow.

## Candidate merge and curation

`RegistryAssembler` merges candidates by normalized LEI. GLEIF wins identity fields, regulator sources win banking jurisdiction and classification fields, and every source identifier remains attached to the resulting stable institution ID. Records without an LEI are retained under a source-scoped key and are never guessed into an existing institution. Conflicts are returned in `MergeReport.conflicts` for review.

```python
from financial_registry.merge import RegistryAssembler

assembler = RegistryAssembler(source_definitions, successful_source_runs)
report = assembler.assemble_with_report(gleif_candidates + fdic_candidates + ecb_candidates)
registry = report.registry
```

The first live pilot is intentionally not a global coverage release: it combines a bounded FDIC sample, its matching GLEIF records, and the current ECB workbook. `data/registry.json` remains the metadata-only institution baseline; the separate `data/registry-with-logos.json` output is the reviewed logo enrichment and may also contain brand-only records that have not yet been linked to a legal entity.

### Bounded source pilot

`source-pilot` is the reproducible entry point for a first real-data run. It
fetches the GLEIF LEI API, FDIC BankFind, and the ECB supervised-entities
workbook, storing each raw response in a content-addressed snapshot directory.
The default limit is 1,000 records per source; increase it only as an explicit
capacity and source-usage decision. The output is a `RegistryInput` JSON file
with normalized institutions, source definitions, successful/failed source
runs, snapshot digests, and merge provenance. Failed sources do not discard
successful sources; they are recorded as warnings in the output.

```bash
financial-registry source-pilot data/registry.json \
  --snapshot-dir data/snapshots \
  --max-records 1000 \
  --generated-at 2026-08-27T00:00:00+00:00
```

Keep `data/snapshots/` outside published release bundles. The generated
registry is still a bounded pilot, not a claim of complete global coverage.

## Logo discovery and rights review

Logo discovery is deliberately separate from downloading and publishing binaries. `OfficialDomainLogoDiscovery` turns the already-curated `Institution.domains` fields into deterministic candidates for common paths (`/logo.svg`, `/favicon.svg`, and `/favicon.ico`). Its `discover_html` parser can also extract same-site `rel=icon`, `apple-touch-icon`, and social-image declarations from HTML fetched by a separately controlled client. Discovery itself performs no network requests and marks every candidate `source_link_only`, because an official website is evidence of where a logo lives—not proof that the logo may be redistributed.

```python
import httpx

from financial_registry.domain import RightsStatus, ReviewStatus
from financial_registry.fetch_policy import SafeHttpxHtmlFetcher, default_dns_resolver
from financial_registry.logo_discovery import LogoRightsReviewer, OfficialDomainLogoDiscovery

discovery = OfficialDomainLogoDiscovery()
candidates = discovery.discover(registry.institutions)

# Fetch HTML with the same HTTPS, DNS-pinning, redirect, and size policy:
with httpx.Client(timeout=10.0) as httpx_client:
    html_fetcher = SafeHttpxHtmlFetcher(httpx_client, default_dns_resolver)
    page = html_fetcher.fetch("https://bank.example/")
    html_candidates = discovery.discover_html(registry.institutions[0], page.final_url, page.body)

# A reviewer supplies evidence for each approved binary, or approves a link-only record.
reviewed = LogoRightsReviewer().review(
    candidates[0],
    decision=ReviewStatus.APPROVED,
    rights_status=RightsStatus.REDISTRIBUTABLE,
    license_name="CC BY 4.0",
    license_url="https://creativecommons.org/licenses/by/4.0/",
)
```

The reviewer requires a license URL or permission reference for `redistributable` approval, a permission reference plus territory coverage for `licensed` approval, and an explicit policy note for `nominative_use` approval. `source_link_only`, `unknown`, and `removed` candidates never become public binaries; only explicitly approved candidates with usable rights evidence may proceed to the existing `AssetProcessor` fetch/sanitize step. This keeps the initial global run useful as a review queue without making an unsupported trademark or copyright claim.

### Promoting reviewed logos

After a human has reviewed the discovery queue, keep the decisions in a separate
JSON file. The file is an auditable allowlist: every decision names one candidate,
the resulting review and rights states, and any evidence needed to redistribute
the bytes.

```json
{
  "decisions": [
    {
      "candidate_id": "asset_logo_candidate",
      "review_status": "approved",
      "rights_status": "nominative_use",
      "rights_note": "Display only to identify the corresponding institution; no endorsement implied.",
      "reviewed_by": "reviewer@example.com",
      "reviewed_at": "2026-08-27T12:00:00+00:00"
    }
  ]
}
```

Apply the decisions with the bounded, policy-controlled fetcher:

```bash
financial-registry logo-promote \
  data/registry.json \
  dist/logo-candidates.json \
  data/logo-decisions.json \
  data/registry-with-logos.json \
  --asset-root data/assets
```

Approved `redistributable`, `licensed`, and `nominative_use` candidates are
fetched over HTTPS with DNS and redirect checks, sanitized, hashed, and staged
under `asset_root/logos/`. `nominative_use` does not claim an open copyright
licence: the policy note travels with the asset and limits downstream use to
identifying the corresponding institution without implying endorsement.
The updated registry points to the staged binary and retains the rights evidence.
An approved `source_link_only` decision emits metadata and the source URL only;
it never downloads or writes a public binary. Candidates without a decision, or
with a non-approved decision, remain out of the asset list and are reported as
warnings. The command fails closed on unknown candidate IDs, duplicate decisions,
missing registry provenance, unsupported formats, and insufficient rights evidence.

The checked-in logo pilot (`data/logo-candidates-simple-icons.json` and
`data/logo-decisions.json`) promotes eleven pinned Simple Icons v16.21.0 SVGs
for Bank of America, Chase, Wells Fargo, Deutsche Bank, Commerzbank, CaixaBank,
HSBC, Barclays, Goldman Sachs, Revolut, and Wise. A second queue
(`data/logo-candidates-official-png.json`) adds four official-site PNG app marks
for Bank of America, JPMorgan Chase, Wells Fargo, and Capital One.

The expansion queues add 25 global financial brand SVGs from the same pinned
Simple Icons release (`data/logo-brand-records.json`,
`data/logo-candidates-simple-icons-brand-expansion.json`), 18 additional
institution assets discovered from official HTML declarations
(`data/logo-candidates-official-html-expansion.json`,
`data/logo-candidates-official-html-logo-expansion.json`), and 81 Indian and
international bank marks from the reviewed
[`auraveni/global-bank-logos`](https://github.com/auraveni/global-bank-logos)
queue (`data/logo-brand-records-auraveni-global-bank-logos.json`,
`data/logo-candidates-auraveni-global-bank-logos.json`). The derived registry
currently contains 135 binary assets (118 SVG, 15 PNG, and 2 JPEG), all
explicitly reviewed as `nominative_use`, not as open-licensed artwork. Source
versions, source URLs, and upstream legal notices are retained with each asset;
the [Simple Icons disclaimer](https://github.com/simple-icons/simple-icons/blob/develop/DISCLAIMER.md)
is retained alongside the pinned Simple Icons assets;
the Auraveni MIT licence is treated as applying to repository code, not to the
bank artwork or trademarks. Downstream use is limited to identifying the
corresponding institution or brand without implying endorsement or affiliation.
The derived registry and staged binaries are in
`data/registry-with-logos.json` and `data/assets/logos/`.

`nominative_use` is intended for an upstream source that documents this narrow
identification-only basis—for example, the [`logos-bancos-br`](https://github.com/rzmt/logos-bancos-br)
dataset. It is not an open copyright licence: published assets retain their
institutional trademark ownership, provenance, use restrictions, and takedown
metadata. Downstream applications must not imply affiliation or endorsement.

### Wikidata and Wikimedia Commons metadata

`WikidataCommonsLogoConnector` is a secondary, metadata-only source. It accepts an explicit institution-to-Wikidata mapping, reads the [logo image (P154)](https://www.wikidata.org/wiki/Property:P154) claim, and asks the [Commons imageinfo API](https://www.mediawiki.org/wiki/API:Imageinfo) for the file URL, license fields, and attribution. It never requests the image URL itself. Commons license metadata is retained as evidence, but the resulting candidate is still `source_link_only` until reviewed.

```python
from financial_registry.logo_sources import WikidataCommonsLogoConnector

result = WikidataCommonsLogoConnector().discover({
    "inst_example_bank": "Q123456",
})
for candidate in result.candidates:
    print(candidate.source_uri, candidate.license_name, candidate.attribution_text)
```

#### Wikidata entity matching queue

Name search is useful for finding possible entities, but it is not safe as an
automatic identity link: banks reuse names across countries, subsidiaries, and
historical entities. `WikidataEntityMatcher` calls Wikidata's
[`wbsearchentities` API](https://www.wikidata.org/w/api.php?action=help&modules=wbsearchentities)
and emits ranked Q-ID suggestions with the returned label, description, exact
label-match flag, and source URI. It never writes an institution-to-Q-ID
mapping. Review the queue and promote only confirmed pairs into the explicit
mapping accepted by `WikidataCommonsLogoConnector`.

```python
from financial_registry.wikidata_matching import WikidataEntityMatcher

result = WikidataEntityMatcher(max_results=5).suggest(registry.institutions)
for suggestion in result.suggestions:
    print(suggestion.institution_id, suggestion.qid, suggestion.label, suggestion.description)
for warning in result.warnings:
    print("review:", warning)
```

The equivalent CLI command writes deterministic JSON for a review workflow:

```bash
financial-registry wikidata-suggest \
  data/fixtures/candidates.json dist/wikidata-suggestions.json \
  --max-results 5
```

The output is advisory evidence only. A reviewer still needs to verify the
country, legal identity, aliases, and current/historical status before adding a
Q-ID to the logo-source mapping.

#### Reviewed mapping allowlist

After review, keep approved links in a separate mapping file. The loader fails
closed on unknown institution IDs, invalid Q-IDs, duplicate institutions, and
duplicate Q-IDs:

```json
{
  "mappings": [
    {
      "institution_id": "inst_hsbc",
      "qid": "Q190464",
      "review_status": "approved",
      "reviewed_by": "reviewer@example.com",
      "reviewed_at": "2026-08-27T12:00:00+00:00"
    }
  ]
}
```

Only records with `review_status: "approved"` are accepted. Feed that
allowlist into the metadata-only logo connector with:

```bash
financial-registry wikidata-logo-discover \
  data/registry.json data/wikidata-mappings.json \
  dist/wikidata-logo-candidates.json
```

The command writes `{ "candidates": [...], "warnings": [...] }`. Candidates
remain `source_link_only` and contain no downloaded image bytes; the existing
rights-review workflow must approve any binary before publication.

## CI

Standalone workflow `.github/workflows/registry-core.yml` runs on Python 3.10-3.12, installs `global-financial-registry[dev]`, runs `ruff`, `pytest`, and coverage (85% threshold) without importing the Relay application.

## License

Apache-2.0 (see `LICENSE`). Normalized metadata: CC BY 4.0.
