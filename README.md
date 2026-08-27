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
financial-registry logo-discover data/fixtures/candidates.json dist/logo-candidates.json
```

### Guarantees

- **Source of truth:** The published release bundle (`institutions.json`, `brands.json`, `identifiers.json`, `aliases.json`, `rekey-events.json`, `relationships.json`, `assets-manifest.json`, `sources.json`, `checksums.txt`, `schema-version.json`) is the only publication output.
- **Rights gate:** Binary assets are emitted only for `redistributable` and `licensed` rights states. `source_link_only` emits metadata and a source URI without a public binary. `unknown`, `removed`, and `source_link_only` assets never emit a public binary; licensed assets require `permission_reference`, territory coverage, and a non-expired permission.
- **Source ingestion:** `GLEIFConnector` fetches a bounded, replayable slice of the public GLEIF LEI API into a content-addressed snapshot, then normalizes LEI, BIC, registration, name, and jurisdiction data into `CandidateRecord` values. Regulator-specific crawlers remain separate adapters.
- **Identity:** Every institution has a curated `canonical_key`; source identifiers are aliases and `RekeyEvent` preserves history without changing the canonical ID. Brand ownership is via sourced `Relationship(brand_of)`.
- **Provenance:** Every published record references a source and successful `SourceRun`. Source failures preserve the prior verified snapshot as warnings.
- **Determinism:** Same input and explicit `--generated-at` produce byte-identical outputs; builds are atomic via temporary directories and `checksums.txt`. `schema-version.json` describes the other files (it is excluded from its own manifest to avoid a self-hash cycle), while `checksums.txt` records its actual digest. Populated output directories are rejected; an empty caller-created directory is allowed.
- **Lifecycle:** `draft -> validated -> published -> superseded` and `published -> withdrawn` with predecessor/successor/withdrawal metadata. Only a validated bundle may be published.
- **Coverage disclaimer:** This fixture-only core makes no global coverage claim and publishes counts, unresolved matches, stale sources, and provenance gaps in `schema-version.json`. Raw snapshots are stored outside public releases.
- **Licensing:** Code is Apache-2.0; project-created normalized metadata is CC BY 4.0 (attribution required); third-party assets retain per-asset rights terms.
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

The first live pilot is intentionally not a global coverage release: it combines a bounded FDIC sample, its matching GLEIF records, and the current ECB workbook. It creates a valid metadata release, but it contains no logo binaries until the logo rights workflow is completed.

## Logo discovery and rights review

Logo discovery is deliberately separate from downloading and publishing binaries. `OfficialDomainLogoDiscovery` turns the already-curated `Institution.domains` fields into deterministic candidates for common paths (`/logo.svg`, `/favicon.svg`, and `/favicon.ico`). It performs no network requests and marks every candidate `source_link_only`, because an official website is evidence of where a logo lives—not proof that the logo may be redistributed.

```python
from financial_registry.domain import RightsStatus, ReviewStatus
from financial_registry.logo_discovery import LogoRightsReviewer, OfficialDomainLogoDiscovery

discovery = OfficialDomainLogoDiscovery()
candidates = discovery.discover(registry.institutions)

# A reviewer supplies evidence for each approved binary, or approves a link-only record.
reviewed = LogoRightsReviewer().review(
    candidates[0],
    decision=ReviewStatus.APPROVED,
    rights_status=RightsStatus.REDISTRIBUTABLE,
    license_name="CC BY 4.0",
    license_url="https://creativecommons.org/licenses/by/4.0/",
)
```

The reviewer requires a license URL or permission reference for `redistributable` approval, and a permission reference plus territory coverage for `licensed` approval. `source_link_only`, `unknown`, and `removed` candidates never become public binaries; only explicitly approved candidates with usable rights evidence may proceed to the existing `AssetProcessor` fetch/sanitize step. This keeps the initial global run useful as a review queue without making an unsupported trademark or copyright claim.

## CI

Standalone workflow `.github/workflows/registry-core.yml` runs on Python 3.10-3.12, installs `global-financial-registry[dev]`, runs `ruff`, `pytest`, and coverage (85% threshold) without importing the Relay application.

## License

Apache-2.0 (see `LICENSE`). Normalized metadata: CC BY 4.0.
