import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import httpx
import typer
from pydantic import ValidationError

from .assets import AssetProcessor
from .connectors import ECBConnector, FDICConnector, GLEIFConnector
from .domain import RegistryInput
from .fetch_policy import AssetPolicyError, SafeHttpxAssetFetcher, default_dns_resolver
from .logo_derivatives import LogoDerivativeError, derive_logo_variants
from .logo_discovery import OfficialDomainLogoDiscovery
from .logo_promotion import (
    load_logo_candidates,
    load_logo_review_decisions,
    promote_reviewed_logos,
)
from .logo_sources import WikidataCommonsLogoConnector
from .pilot import run_registry_pilot
from .release import ReleaseBuilder, ReleaseValidationError
from .snapshots import FilesystemSnapshotStore
from .wikidata_mapping import load_reviewed_wikidata_mappings
from .wikidata_matching import WikidataEntityMatcher

app = typer.Typer(no_args_is_help=True)


def _resolve_input_path(path: str) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p.resolve()
    # Try relative to cwd
    cwd_candidate = (Path.cwd() / p).resolve()
    if cwd_candidate.exists():
        return cwd_candidate
    # Try relative to package root (for tests running from different cwd)
    pkg_root = Path(__file__).resolve().parents[2]
    alt2 = (pkg_root / p).resolve() if (pkg_root / p).exists() else None
    if alt2 and alt2.exists():
        return alt2
    # Fallback to resolve relative to cwd (will raise FileNotFound later)
    return p.resolve()


def _load(path: str) -> RegistryInput:
    input_path = _resolve_input_path(path)
    registry = RegistryInput.model_validate(json.loads(input_path.read_text(encoding="utf-8")))
    if registry.asset_root and not Path(registry.asset_root).is_absolute():
        # Resolve relative to input file's parent
        # Also handle case where asset_root is "logos" and input is in data/fixtures
        resolved = (input_path.parent / registry.asset_root).resolve()
        registry = registry.model_copy(update={"asset_root": str(resolved)})
    return registry


def _registry_payload(registry: RegistryInput, output: Path) -> dict:
    """Serialize a registry while keeping colocated snapshots portable."""

    payload = registry.model_dump(mode="json")
    output_parent = output.resolve().parent
    for source_run in payload.get("source_runs", []):
        snapshot_path = source_run.get("snapshot_path")
        if not snapshot_path:
            continue
        try:
            snapshot = Path(snapshot_path)
            if not snapshot.is_absolute():
                snapshot = output_parent / snapshot
            source_run["snapshot_path"] = str(snapshot.resolve().relative_to(output_parent))
        except ValueError:
            # A caller may intentionally keep snapshots outside the registry's directory.
            continue
    asset_root = payload.get("asset_root")
    if asset_root:
        try:
            root = Path(asset_root)
            if not root.is_absolute():
                root = output_parent / root
            payload["asset_root"] = str(root.resolve().relative_to(output_parent))
        except ValueError:
            # A caller may intentionally keep assets outside the registry's directory.
            pass
    return payload


@app.command("validate")
def validate(input_path: str = typer.Argument(...)) -> None:
    try:
        registry = _load(input_path)
        issues = ReleaseBuilder().validate(registry, generation_commit="validation")
    except FileNotFoundError as exc:
        typer.echo(f"error[input_not_found] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except (json.JSONDecodeError, ValidationError) as exc:
        typer.echo(f"error[input_invalid] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except ReleaseValidationError as exc:
        typer.echo(f"error[release_invalid] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except OSError as exc:
        typer.echo(f"error[release_io] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except ValueError as exc:
        typer.echo(f"error[release_invalid] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if issues:
        for issue in issues:
            typer.echo(f"error[release_invalid] {issue}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"valid: {input_path}")


@app.command("release-build")
def release_build(
    input_path: str = typer.Argument(...),
    output_dir: str = typer.Argument(...),
    version: str = typer.Option(..., "--version"),
    generated_at: str = typer.Option(..., "--generated-at"),
    generation_commit: str = typer.Option(..., "--generation-commit"),
) -> None:
    try:
        registry = _load(input_path)
        timestamp = datetime.fromisoformat(generated_at)
        manifest = ReleaseBuilder().build(
            registry,
            version,
            timestamp,
            Path(output_dir),
            generation_commit=generation_commit,
        )
    except FileNotFoundError as exc:
        typer.echo(f"error[input_not_found] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except (json.JSONDecodeError, ValidationError) as exc:
        typer.echo(f"error[input_invalid] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except ReleaseValidationError as exc:
        typer.echo(f"error[release_invalid] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except OSError as exc:
        typer.echo(f"error[release_io] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except ValueError as exc:
        typer.echo(f"error[release_invalid] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"release {manifest.release_version}: {output_dir}")


@app.command("source-pilot")
def source_pilot(
    output_path: str = typer.Argument(...),
    snapshot_dir: str = typer.Option("data/snapshots", "--snapshot-dir"),
    max_records: int = typer.Option(1_000, "--max-records", min=1, max=10_000),
    generated_at: str | None = typer.Option(None, "--generated-at"),
) -> None:
    """Fetch bounded GLEIF, FDIC, and ECB data and write a merged registry."""

    try:
        run_at = datetime.fromisoformat(generated_at) if generated_at else datetime.now(timezone.utc)
        snapshot_store = FilesystemSnapshotStore(snapshot_dir)
        connectors = (
            GLEIFConnector(
                snapshot_store,
                max_records=max_records,
                filters={"entity.status": "ACTIVE"},
            ),
            FDICConnector(snapshot_store, max_records=max_records),
            ECBConnector(snapshot_store, max_records=max_records),
        )
        result = run_registry_pilot(connectors, now=run_at)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                _registry_payload(result.registry, output),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        typer.echo(f"error[pilot_invalid] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except OSError as exc:
        typer.echo(f"error[pilot_io] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"source pilot: {len(result.registry.institutions)} institutions, "
        f"{result.report.candidate_count} candidates, {len(result.warnings)} warnings -> {output_path}"
    )


@app.command("logo-discover")
def logo_discover(
    input_path: str = typer.Argument(...),
    output_path: str = typer.Argument(...),
) -> None:
    """Write a deterministic, source-link-only logo review queue."""

    try:
        registry = _load(input_path)
        candidates = OfficialDomainLogoDiscovery().discover(registry.institutions)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = [candidate.model_dump(mode="json") for candidate in candidates]
        output.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    except FileNotFoundError as exc:
        typer.echo(f"error[input_not_found] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        typer.echo(f"error[input_invalid] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except OSError as exc:
        typer.echo(f"error[output_io] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"logo discovery: {len(candidates)} candidates -> {output_path}")


@app.command("logo-promote")
def logo_promote(
    input_path: str = typer.Argument(...),
    candidates_path: str = typer.Argument(...),
    decisions_path: str = typer.Argument(...),
    output_path: str = typer.Argument(...),
    asset_root: str | None = typer.Option(None, "--asset-root"),
) -> None:
    """Apply explicit logo rights decisions and write an updated registry."""

    try:
        registry = _load(input_path)
        candidates = load_logo_candidates(_resolve_input_path(candidates_path))
        decisions = load_logo_review_decisions(_resolve_input_path(decisions_path))
        output = Path(output_path)
        resolved_asset_root = asset_root if asset_root is not None else registry.asset_root
        with httpx.Client(timeout=10.0) as httpx_client:
            result = promote_reviewed_logos(
                registry,
                candidates,
                decisions,
                fetcher=SafeHttpxAssetFetcher(httpx_client, default_dns_resolver),
                processor=AssetProcessor(),
                asset_root=resolved_asset_root,
                clock=lambda: datetime.now(timezone.utc),
            )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                _registry_payload(result.registry, output),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
    except FileNotFoundError as exc:
        typer.echo(f"error[input_not_found] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except (json.JSONDecodeError, ValidationError) as exc:
        typer.echo(f"error[logo_invalid] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except (httpx.HTTPError, AssetPolicyError) as exc:
        typer.echo(f"error[logo_fetch] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except ValueError as exc:
        typer.echo(f"error[logo_invalid] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except OSError as exc:
        typer.echo(f"error[output_io] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"logo promotion: {len(result.assets)} assets, {len(result.warnings)} warnings -> {output_path}"
    )


@app.command("logo-derive")
def logo_derive(
    input_path: str = typer.Argument(...),
    output_path: str = typer.Argument(...),
    formats: str = typer.Option("png,webp,jpg", "--formats"),
    width: int = typer.Option(512, "--width", min=1, max=4096),
    asset_root: str | None = typer.Option(None, "--asset-root"),
) -> None:
    """Generate compatibility raster derivatives from approved SVG assets."""

    try:
        registry = _load(input_path)
        requested_formats = tuple(value.strip() for value in formats.split(",") if value.strip())
        derived = derive_logo_variants(
            registry,
            asset_root=asset_root,
            formats=requested_formats,
            width=width,
        )
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                _registry_payload(derived, output),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
    except FileNotFoundError as exc:
        typer.echo(f"error[input_not_found] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except (json.JSONDecodeError, ValidationError, LogoDerivativeError, ValueError) as exc:
        typer.echo(f"error[logo_derivative] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except OSError as exc:
        typer.echo(f"error[output_io] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"logo derivatives: {len(derived.assets) - len(registry.assets)} assets -> {output_path}")


@app.command("wikidata-suggest")
def wikidata_suggest(
    input_path: str = typer.Argument(...),
    output_path: str = typer.Argument(...),
    max_results: int = typer.Option(5, "--max-results", min=1, max=50),
) -> None:
    """Write a ranked, human-reviewable Wikidata entity suggestion queue."""

    try:
        registry = _load(input_path)
        result = WikidataEntityMatcher(max_results=max_results).suggest(registry.institutions)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "suggestions": [asdict(suggestion) for suggestion in result.suggestions],
            "warnings": list(result.warnings),
        }
        output.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    except FileNotFoundError as exc:
        typer.echo(f"error[input_not_found] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        typer.echo(f"error[input_invalid] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except httpx.HTTPError as exc:
        typer.echo(f"error[wikidata_fetch] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except OSError as exc:
        typer.echo(f"error[output_io] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"wikidata suggestions: {len(result.suggestions)} suggestions, "
        f"{len(result.warnings)} warnings -> {output_path}"
    )


@app.command("wikidata-logo-discover")
def wikidata_logo_discover(
    input_path: str = typer.Argument(...),
    mapping_path: str = typer.Argument(...),
    output_path: str = typer.Argument(...),
) -> None:
    """Discover Commons logo metadata for an approved Wikidata mapping file."""

    try:
        registry = _load(input_path)
        mappings = load_reviewed_wikidata_mappings(_resolve_input_path(mapping_path), registry)
        result = WikidataCommonsLogoConnector().discover(mappings)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "candidates": [candidate.model_dump(mode="json") for candidate in result.candidates],
            "warnings": list(result.warnings),
        }
        output.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    except FileNotFoundError as exc:
        typer.echo(f"error[input_not_found] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        typer.echo(f"error[input_invalid] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except httpx.HTTPError as exc:
        typer.echo(f"error[wikidata_fetch] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except OSError as exc:
        typer.echo(f"error[output_io] {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"wikidata logo discovery: {len(result.candidates)} candidates, "
        f"{len(result.warnings)} warnings -> {output_path}"
    )


def main() -> None:
    app()
