"""Build and verify a deterministic, reviewable logo linkage manifest."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

from .domain import RegistryInput


class LogoManifestError(ValueError):
    """Raised when registry assets cannot be represented by the manifest."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_staging_path(value: str | None) -> PurePosixPath:
    if not value:
        raise LogoManifestError("asset is missing staging_path")
    normalized = value.replace("\\", "/")
    if any(part == "" for part in normalized.split("/")):
        raise LogoManifestError(f"unsafe staging_path: {value}")
    path = PurePosixPath(normalized)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise LogoManifestError(f"unsafe staging_path: {value}")
    return path


def _resolve_asset_root(registry_path: Path, asset_root: str | None) -> Path:
    if not asset_root:
        raise LogoManifestError("registry is missing asset_root")
    root = Path(asset_root)
    return root.resolve() if root.is_absolute() else (registry_path.parent / root).resolve()


def _owner_kind(registry: RegistryInput, owner_id: str) -> str:
    institution_ids = {item.id for item in registry.institutions}
    brand_ids = {item.id for item in registry.brands}
    if owner_id in institution_ids:
        return "institution"
    if owner_id in brand_ids:
        return "brand"
    raise LogoManifestError(f"asset references unknown owner_id: {owner_id}")


def build_logo_manifest(registry_path: Path, *, registry_label: str | None = None) -> dict[str, Any]:
    """Return a deterministic manifest proving each asset's local linkage."""

    registry_path = Path(registry_path).resolve()
    try:
        raw = registry_path.read_bytes()
        registry = RegistryInput.model_validate(json.loads(raw))
    except FileNotFoundError as exc:
        raise LogoManifestError(f"registry not found: {registry_path}") from exc
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        raise LogoManifestError(f"registry is invalid: {exc}") from exc

    owner_ids = {item.id for item in registry.institutions} | {item.id for item in registry.brands}
    source_ids = {item.id for item in registry.sources}
    asset_root = _resolve_asset_root(registry_path, registry.asset_root)
    entries: list[dict[str, Any]] = []

    for asset in sorted(registry.assets, key=lambda item: item.id):
        owner_kind = _owner_kind(registry, asset.owner_id)
        if asset.source_id not in source_ids:
            raise LogoManifestError(f"asset references unknown source_id: {asset.source_id}")
        if asset.owner_id not in owner_ids:
            raise LogoManifestError(f"asset references unknown owner_id: {asset.owner_id}")
        relative_path = _safe_staging_path(asset.staging_path)
        original_path = asset_root / Path(*relative_path.parts)
        if original_path.is_symlink():
            raise LogoManifestError(f"staging file is missing or symlinked: {asset.staging_path}")
        local_path = original_path.resolve()
        try:
            local_path.relative_to(asset_root)
        except ValueError as exc:
            raise LogoManifestError(f"staging_path escapes asset root: {asset.staging_path}") from exc
        if not local_path.is_file():
            raise LogoManifestError(f"staging file is missing or symlinked: {asset.staging_path}")
        actual_sha256 = _sha256(local_path)
        if asset.sha256 != actual_sha256:
            raise LogoManifestError(
                f"checksum mismatch for {asset.staging_path}: expected {asset.sha256}, got {actual_sha256}"
            )
        if asset.rights_status.value == "nominative_use" and not asset.rights_note:
            raise LogoManifestError(f"nominative-use asset is missing rights_note: {asset.id}")
        if not asset.source_uri:
            raise LogoManifestError(f"asset is missing source_uri: {asset.id}")
        entries.append(
            {
                "asset_id": asset.id,
                "owner_id": asset.owner_id,
                "owner_kind": owner_kind,
                "source_id": asset.source_id,
                "rights_status": asset.rights_status.value,
                "review_status": asset.review_status.value,
                "binary_path": asset.binary_path,
                "staging_path": relative_path.as_posix(),
                "sha256": actual_sha256,
                "bytes": local_path.stat().st_size,
            }
        )

    return {
        "schema_version": 1,
        "registry_path": registry_label or registry_path.name,
        "registry_sha256": hashlib.sha256(raw).hexdigest(),
        "asset_root": registry.asset_root,
        "asset_count": len(entries),
        "owner_count": len(owner_ids),
        "source_count": len(source_ids),
        "format_counts": dict(sorted(Counter(asset.format.value for asset in registry.assets).items())),
        "rights_counts": dict(sorted(Counter(asset.rights_status.value for asset in registry.assets).items())),
        "assets": entries,
    }


def serialize_logo_manifest(manifest: dict[str, Any]) -> str:
    """Serialize summaries compactly while keeping each asset entry reviewable."""

    assets = manifest.get("assets")
    if not isinstance(assets, list):
        raise LogoManifestError("manifest assets must be a list")
    lines = ["{"]
    summary = {key: value for key, value in manifest.items() if key != "assets"}
    summary_items = sorted(summary.items())
    has_assets_key = "assets" in manifest
    for index, (key, value) in enumerate(summary_items):
        comma = "," if index < len(summary_items) - 1 or has_assets_key else ""
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        lines.append(f"  {json.dumps(key, ensure_ascii=False)}: {encoded}{comma}")
    lines.append('  "assets": [')
    for index, asset in enumerate(assets):
        comma = "," if index < len(assets) - 1 else ""
        encoded = json.dumps(asset, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        lines.append(f"    {encoded}{comma}")
    lines.extend(["  ]", "}"])
    return "\n".join(lines) + "\n"


def verify_logo_manifest(registry_path: Path, manifest_path: Path) -> dict[str, Any]:
    """Rebuild and compare a checked-in manifest against the current registry."""

    manifest_path = Path(manifest_path)
    try:
        actual = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        raise LogoManifestError(f"manifest is unreadable: {manifest_path}") from exc
    if not isinstance(actual, dict):
        raise LogoManifestError(f"manifest must be a JSON object: {manifest_path}")
    expected = build_logo_manifest(registry_path, registry_label=actual.get("registry_path"))
    if actual != expected:
        raise LogoManifestError("manifest does not match registry, assets, or linkage metadata")
    return actual
