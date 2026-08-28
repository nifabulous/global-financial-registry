"""Build and verify the lightweight data projection used by the logo gallery."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class GalleryDataError(ValueError):
    """Raised when a registry cannot be projected into gallery data."""


def _read_registry(registry_path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = registry_path.read_bytes()
        registry = json.loads(raw)
    except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError) as exc:
        raise GalleryDataError(f"registry is unreadable: {registry_path}") from exc
    if not isinstance(registry, dict):
        raise GalleryDataError("registry must be a JSON object")
    for key in ("institutions", "brands", "assets", "sources"):
        if not isinstance(registry.get(key), list):
            raise GalleryDataError(f"registry field {key} must be a list")
    return registry, raw


def _sorted_entities(values: list[Any], included_ids: set[str]) -> list[dict[str, Any]]:
    entities = [
        value for value in values
        if isinstance(value, dict) and isinstance(value.get("id"), str) and value["id"] in included_ids
    ]
    return sorted(entities, key=lambda value: value["id"])


def build_gallery_data(registry_path: Path) -> dict[str, Any]:
    """Return a deterministic projection containing only logo-linked records."""

    registry_path = Path(registry_path).resolve()
    registry, raw = _read_registry(registry_path)
    assets = sorted(
        [value for value in registry["assets"] if isinstance(value, dict)],
        key=lambda value: value.get("id", ""),
    )
    owner_ids = {value.get("owner_id") for value in assets if isinstance(value.get("owner_id"), str)}
    source_ids = {value.get("source_id") for value in assets if isinstance(value.get("source_id"), str)}
    institutions = _sorted_entities(registry["institutions"], owner_ids)
    brands = _sorted_entities(registry["brands"], owner_ids)
    known_owner_ids = {value["id"] for value in institutions + brands}
    if missing_owners := sorted(owner_ids - known_owner_ids):
        raise GalleryDataError(f"assets reference unknown owners: {', '.join(missing_owners)}")
    sources = _sorted_entities(registry["sources"], source_ids)
    known_source_ids = {value["id"] for value in sources}
    if missing_sources := sorted(source_ids - known_source_ids):
        raise GalleryDataError(f"assets reference unknown sources: {', '.join(missing_sources)}")

    return {
        "asset_root": registry.get("asset_root"),
        "assets": assets,
        "brands": brands,
        "coverage": {"total_entities": len(registry["institutions"]) + len(registry["brands"])},
        "institutions": institutions,
        "registry_sha256": hashlib.sha256(raw).hexdigest(),
        "schema_version": 1,
        "sources": sources,
    }


def serialize_gallery_data(data: dict[str, Any]) -> str:
    """Serialize gallery data with stable ordering and a trailing newline."""

    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def verify_gallery_data(registry_path: Path, gallery_path: Path) -> dict[str, Any]:
    """Verify a checked-in gallery projection against its source registry."""

    try:
        actual = json.loads(Path(gallery_path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        raise GalleryDataError(f"gallery data is unreadable: {gallery_path}") from exc
    if not isinstance(actual, dict):
        raise GalleryDataError("gallery data must be a JSON object")
    expected = build_gallery_data(registry_path)
    if actual != expected:
        raise GalleryDataError("gallery data does not match the source registry")
    return actual
