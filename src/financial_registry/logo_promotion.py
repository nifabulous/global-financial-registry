"""Rights-reviewed logo promotion into registry assets."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .assets import AssetFetcher, AssetProcessor, ProcessedAsset
from .domain import (
    Asset,
    AssetCandidate,
    AssetFormat,
    RegistryInput,
    ReviewStatus,
    RightsStatus,
)
from .fetch_policy import FetchedAsset
from .logo_discovery import LogoRightsReviewer


class LogoReviewDecision(BaseModel):
    """One explicit rights and review decision for a logo candidate."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1)
    review_status: ReviewStatus
    rights_status: RightsStatus
    license_name: str | None = None
    license_url: str | None = None
    permission_reference: str | None = None
    territories: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    rights_note: str | None = None
    attribution_text: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None

    @field_validator("candidate_id", mode="before")
    @classmethod
    def strip_candidate_id(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator(
        "license_name",
        "license_url",
        "permission_reference",
        "rights_note",
        "attribution_text",
        "reviewed_by",
        mode="before",
    )
    @classmethod
    def strip_optional_text(cls, value):
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        return cleaned or None

    @field_validator("territories")
    @classmethod
    def validate_territories(cls, values):
        for value in values:
            if not isinstance(value, str) or len(value) != 2 or not value.isascii() or value != value.upper():
                raise ValueError("territories must contain uppercase ISO-like alpha-2 codes")
        return values

    @field_validator("expires_at", "reviewed_at")
    @classmethod
    def validate_timestamps(cls, value):
        if value is not None and (
            value.tzinfo is None
            or value.utcoffset() is None
            or value.utcoffset() != timezone.utc.utcoffset(value)
        ):
            raise ValueError("review timestamps must be timezone-aware UTC")
        return value


class LogoReviewFile(BaseModel):
    """JSON envelope for logo review decisions."""

    model_config = ConfigDict(extra="forbid")

    decisions: list[LogoReviewDecision]


@dataclass(frozen=True)
class LogoPromotionResult:
    """Updated registry, reviewed candidates, and non-fatal promotion warnings."""

    registry: RegistryInput
    assets: tuple[Asset, ...]
    reviewed_candidates: tuple[AssetCandidate, ...]
    warnings: tuple[str, ...] = ()


class LogoPromotionError(ValueError):
    """Raised when an approved logo cannot be safely materialized."""


class _CapturingFetcher:
    def __init__(self, delegate: AssetFetcher):
        self.delegate = delegate
        self.fetched: FetchedAsset | None = None

    def fetch(self, url: str) -> FetchedAsset:
        fetched = self.delegate.fetch(url)
        self.fetched = fetched
        return fetched


def load_logo_candidates(path: str | Path) -> tuple[AssetCandidate, ...]:
    """Load either a candidate list or a ``{\"candidates\": [...]}`` envelope."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_candidates = payload.get("candidates") if isinstance(payload, Mapping) else payload
    if not isinstance(raw_candidates, list):
        raise ValueError("logo candidate input must be a list or an object with candidates")
    return tuple(AssetCandidate.model_validate(item) for item in raw_candidates)


def load_logo_review_decisions(path: str | Path) -> tuple[LogoReviewDecision, ...]:
    """Load the explicit rights decisions envelope."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return tuple(LogoReviewFile.model_validate(payload).decisions)


def promote_reviewed_logos(
    registry: RegistryInput,
    candidates: Iterable[AssetCandidate],
    decisions: Iterable[LogoReviewDecision],
    *,
    fetcher: AssetFetcher,
    processor: AssetProcessor | None = None,
    reviewer: LogoRightsReviewer | None = None,
    asset_root: str | Path | None = None,
    clock=None,
) -> LogoPromotionResult:
    """Apply decisions and materialize only explicitly approved logo assets."""

    clock = clock or (lambda: datetime.now(timezone.utc))
    processor = processor or AssetProcessor()
    reviewer = reviewer or LogoRightsReviewer(clock=clock)
    candidate_map: dict[str, AssetCandidate] = {}
    for candidate in candidates:
        if not candidate.id:
            raise LogoPromotionError("logo candidate is missing a stable id")
        _validate_asset_id(candidate.id)
        if candidate.id in candidate_map:
            raise LogoPromotionError(f"duplicate logo candidate id: {candidate.id}")
        candidate_map[candidate.id] = candidate

    decision_map: dict[str, LogoReviewDecision] = {}
    for decision in decisions:
        if decision.candidate_id not in candidate_map:
            raise LogoPromotionError(f"unknown logo candidate in decision: {decision.candidate_id}")
        if decision.candidate_id in decision_map:
            raise LogoPromotionError(f"duplicate logo decision: {decision.candidate_id}")
        decision_map[decision.candidate_id] = decision

    entity_ids = {item.id for item in registry.institutions} | {item.id for item in registry.brands}
    source_ids = {source.id for source in registry.sources}
    existing_asset_ids = {asset.id for asset in registry.assets}
    root = Path(asset_root if asset_root is not None else registry.asset_root).resolve() if (asset_root or registry.asset_root) else None
    promoted: list[Asset] = []
    reviewed: list[AssetCandidate] = []
    warnings: list[str] = []

    for candidate_id in sorted(candidate_map):
        decision = decision_map.get(candidate_id)
        if decision is None:
            warnings.append(f"{candidate_id} has no logo review decision")
            continue
        candidate = candidate_map[candidate_id]
        reviewed_candidate = reviewer.review(
            candidate,
            decision=decision.review_status,
            rights_status=decision.rights_status,
            license_name=decision.license_name,
            license_url=decision.license_url,
            permission_reference=decision.permission_reference,
            territories=decision.territories,
            expires_at=decision.expires_at,
            rights_note=decision.rights_note,
            attribution_text=decision.attribution_text,
            reviewed_by=decision.reviewed_by,
            reviewed_at=decision.reviewed_at,
        )
        reviewed.append(reviewed_candidate)
        if reviewed_candidate.review_status is not ReviewStatus.APPROVED:
            warnings.append(f"{candidate_id} was not approved; no asset emitted")
            continue
        if reviewed_candidate.owner_id not in entity_ids:
            raise LogoPromotionError(f"logo candidate owner is not in registry: {reviewed_candidate.owner_id}")
        if reviewed_candidate.source_id not in source_ids:
            raise LogoPromotionError(f"logo candidate source is not in registry: {reviewed_candidate.source_id}")
        if reviewed_candidate.id in existing_asset_ids:
            raise LogoPromotionError(f"logo asset id already exists in registry: {reviewed_candidate.id}")

        processed: ProcessedAsset | None = None
        fetched_content_type: str | None = None
        if reviewed_candidate.rights_status is RightsStatus.SOURCE_LINK_ONLY:
            asset_format = _format_from_uri(reviewed_candidate.source_uri)
            if asset_format is None:
                raise LogoPromotionError(
                    f"source-link-only logo has unsupported format: {reviewed_candidate.source_uri}"
                )
        else:
            if root is None:
                raise LogoPromotionError("asset_root is required for public logo binaries")
            capturing_fetcher = _CapturingFetcher(fetcher)
            processed = processor.process(reviewed_candidate, capturing_fetcher)
            if processed.public_binary is None or capturing_fetcher.fetched is None:
                raise LogoPromotionError("approved logo did not produce a public binary")
            fetched_content_type = capturing_fetcher.fetched.content_type
            asset_format = _format_from_content_type(fetched_content_type)
            if asset_format is None:
                raise LogoPromotionError(f"unsupported fetched logo content type: {fetched_content_type}")
            _write_staged_binary(root, reviewed_candidate.id, asset_format, processed.public_binary)

        has_binary = processed is not None and processed.public_binary is not None
        promoted_asset = Asset(
            id=reviewed_candidate.id,
            owner_id=reviewed_candidate.owner_id,
            variant=reviewed_candidate.variant,
            format=asset_format,
            source_id=reviewed_candidate.source_id,
            source_uri=reviewed_candidate.source_uri,
            rights_status=reviewed_candidate.rights_status,
            review_status=reviewed_candidate.review_status,
            sha256=processed.sha256 if has_binary and processed else None,
            perceptual_hash=processed.imagehash if has_binary and processed else None,
            binary_path=f"assets/{reviewed_candidate.id}.{asset_format.value}" if has_binary else None,
            staging_path=f"logos/{reviewed_candidate.id}.{asset_format.value}" if has_binary else None,
            license_name=reviewed_candidate.license_name,
            license_url=reviewed_candidate.license_url,
            permission_reference=reviewed_candidate.permission_reference,
            attribution_text=reviewed_candidate.attribution_text,
            rights_note=reviewed_candidate.rights_note,
            territories=reviewed_candidate.territories,
            expires_at=reviewed_candidate.expires_at,
            verified_at=clock() if has_binary else None,
            reviewed_by=reviewed_candidate.reviewed_by,
            reviewed_at=reviewed_candidate.reviewed_at,
        )
        promoted.append(promoted_asset)
        existing_asset_ids.add(promoted_asset.id)

    all_assets = sorted([*registry.assets, *promoted], key=lambda asset: asset.id)
    updated_registry = registry.model_copy(
        update={
            "assets": all_assets,
            "asset_root": str(root) if root is not None else registry.asset_root,
        }
    )
    return LogoPromotionResult(
        registry=updated_registry,
        assets=tuple(promoted),
        reviewed_candidates=tuple(reviewed),
        warnings=tuple(warnings),
    )


def _format_from_content_type(content_type: str) -> AssetFormat | None:
    return {
        "image/svg+xml": AssetFormat.SVG,
        "image/png": AssetFormat.PNG,
        "image/webp": AssetFormat.WEBP,
    }.get(content_type.casefold().split(";", 1)[0].strip())


def _format_from_uri(source_uri: str) -> AssetFormat | None:
    suffix = Path(urlsplit(source_uri).path).suffix.casefold()
    return {".svg": AssetFormat.SVG, ".png": AssetFormat.PNG, ".webp": AssetFormat.WEBP}.get(suffix)


def _validate_asset_id(asset_id: str) -> None:
    if (
        asset_id in {".", ".."}
        or Path(asset_id).name != asset_id
        or "/" in asset_id
        or "\\" in asset_id
    ):
        raise LogoPromotionError("logo candidate id must be stable path-safe text")


def _write_staged_binary(root: Path, asset_id: str, asset_format: AssetFormat, body: bytes) -> None:
    if root.exists() and root.is_symlink():
        raise LogoPromotionError("asset root must not be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    logos_dir = root / "logos"
    if logos_dir.exists() and logos_dir.is_symlink():
        raise LogoPromotionError("logo staging directory must not be a symlink")
    logos_dir.mkdir(parents=True, exist_ok=True)
    destination = logos_dir / f"{asset_id}.{asset_format.value}"
    if destination.is_symlink():
        raise LogoPromotionError("logo staging path must not be a symlink")
    if destination.exists():
        if destination.read_bytes() != body:
            raise LogoPromotionError(f"logo staging path already contains different bytes: {destination}")
        return
    temporary = destination.with_name(f".{destination.name}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise LogoPromotionError(f"logo staging temporary path already exists: {temporary}")
    with temporary.open("wb") as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(destination)


__all__ = [
    "LogoPromotionError",
    "LogoPromotionResult",
    "LogoReviewDecision",
    "LogoReviewFile",
    "load_logo_candidates",
    "load_logo_review_decisions",
    "promote_reviewed_logos",
]
