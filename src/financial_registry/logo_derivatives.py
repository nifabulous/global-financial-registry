"""Generate compatibility raster assets from approved SVG logo assets."""

from __future__ import annotations

import hashlib
import io
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import cairosvg
from PIL import Image

from .assets import compute_imagehash
from .domain import Asset, AssetFormat, RegistryInput, ReviewStatus, RightsStatus
from .ids import StableIdAllocator


class LogoDerivativeError(ValueError):
    """Raised when an SVG derivative cannot be safely generated."""


_FORMAT_ALIASES = {
    "png": AssetFormat.PNG,
    "webp": AssetFormat.WEBP,
    "jpg": AssetFormat.JPEG,
    "jpeg": AssetFormat.JPEG,
}
_RESTRICTED_RIGHTS = {RightsStatus.SOURCE_LINK_ONLY, RightsStatus.UNKNOWN, RightsStatus.REMOVED}


def derive_logo_variants(
    registry: RegistryInput,
    *,
    asset_root: str | Path | None = None,
    formats: Iterable[AssetFormat | str] = (AssetFormat.PNG, AssetFormat.WEBP, AssetFormat.JPEG),
    width: int = 512,
    id_allocator: StableIdAllocator | None = None,
    clock: Callable[[], datetime] | None = None,
) -> RegistryInput:
    """Create PNG, WebP, and JPEG derivatives for approved SVG assets.

    A derivative keeps the source asset's owner, variant, source, and rights
    policy, while recording the source asset ID in ``derived_from``. Existing
    deterministic derivatives are reused when their bytes and metadata match.
    """

    if not isinstance(width, int) or isinstance(width, bool) or not 1 <= width <= 4096:
        raise LogoDerivativeError("width must be an integer between 1 and 4096")
    requested_formats = _normalize_formats(formats)
    if not requested_formats:
        raise LogoDerivativeError("at least one derivative format is required")
    root = Path(asset_root if asset_root is not None else registry.asset_root) if (asset_root or registry.asset_root) else None
    if root is None:
        raise LogoDerivativeError("asset_root is required for logo derivatives")
    root = root.resolve()
    allocator = id_allocator or StableIdAllocator()
    now = clock or (lambda: datetime.now(timezone.utc))

    existing_by_id = {asset.id: asset for asset in registry.assets}
    generated = list(registry.assets)
    for source in sorted(registry.assets, key=lambda asset: asset.id):
        if (
            source.format is not AssetFormat.SVG
            or source.review_status is not ReviewStatus.APPROVED
            or source.rights_status in _RESTRICTED_RIGHTS
            or not source.staging_path
        ):
            continue
        source_path = _safe_staging_path(root, source.staging_path)
        if not source_path.is_file():
            raise LogoDerivativeError(f"source SVG not found: {source.staging_path}")
        try:
            png_bytes = cairosvg.svg2png(
                bytestring=source_path.read_bytes(),
                output_width=width,
                unsafe=False,
            )
            with Image.open(io.BytesIO(png_bytes)) as image:
                image.load()
                rgba = image.convert("RGBA")
        except Exception as exc:  # pragma: no cover - backend-specific error text
            raise LogoDerivativeError(f"failed to rasterize {source.id}: {exc}") from exc

        for output_format in requested_formats:
            derivative_id = allocator.allocate(
                "asset",
                f"derived:{source.id}:{output_format.value}:width-{width}",
            )
            binary = _encode(rgba, output_format)
            digest = hashlib.sha256(binary).hexdigest()
            existing = existing_by_id.get(derivative_id)
            if existing is not None:
                if existing.sha256 != digest or existing.derived_from != source.id:
                    raise LogoDerivativeError(f"conflicting existing derivative: {derivative_id}")
                continue

            staging_path = f"logos/{derivative_id}.{output_format.value}"
            destination = _safe_staging_path(root, staging_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(binary)
            rights_note = source.rights_note
            derivative_note = (
                f"Generated {output_format.value.upper()} derivative at {width}px from SVG asset {source.id}; "
                "the source asset's rights and use restrictions remain unchanged."
            )
            rights_note = f"{rights_note} {derivative_note}" if rights_note else derivative_note
            derived = Asset(
                id=derivative_id,
                owner_id=source.owner_id,
                variant=source.variant,
                format=output_format,
                source_id=source.source_id,
                source_uri=source.source_uri,
                rights_status=source.rights_status,
                review_status=ReviewStatus.APPROVED,
                sha256=digest,
                perceptual_hash=compute_imagehash(binary, f"image/{output_format.value}"),
                width=rgba.width,
                height=rgba.height,
                binary_path=f"assets/{derivative_id}.{output_format.value}",
                staging_path=staging_path,
                derived_from=source.id,
                license_note=source.license_note,
                license_name=source.license_name,
                license_url=source.license_url,
                permission_reference=source.permission_reference,
                attribution_text=source.attribution_text,
                rights_note=rights_note,
                territories=list(source.territories),
                expires_at=source.expires_at,
                verified_at=now(),
                reviewed_by=source.reviewed_by,
                reviewed_at=source.reviewed_at,
            )
            generated.append(derived)
            existing_by_id[derivative_id] = derived

    return registry.model_copy(update={"assets": sorted(generated, key=lambda asset: asset.id)})


def _normalize_formats(formats: Iterable[AssetFormat | str]) -> tuple[AssetFormat, ...]:
    normalized: list[AssetFormat] = []
    for value in formats:
        key = value.value if isinstance(value, AssetFormat) else str(value).strip().casefold()
        output_format = _FORMAT_ALIASES.get(key)
        if output_format is None:
            raise LogoDerivativeError(f"unsupported derivative format: {value}")
        if output_format not in normalized:
            normalized.append(output_format)
    return tuple(normalized)


def _safe_staging_path(root: Path, staging_path: str) -> Path:
    candidate = Path(staging_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise LogoDerivativeError(f"unsafe staging path: {staging_path}")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise LogoDerivativeError(f"staging path escapes asset root: {staging_path}") from exc
    return resolved


def _encode(image: Image.Image, output_format: AssetFormat) -> bytes:
    encoded = io.BytesIO()
    if output_format is AssetFormat.PNG:
        image.save(encoded, format="PNG", optimize=False)
    elif output_format is AssetFormat.WEBP:
        image.save(encoded, format="WEBP", lossless=True, method=6)
    elif output_format is AssetFormat.JPEG:
        background = Image.new("RGB", image.size, "white")
        background.paste(image, mask=image.getchannel("A"))
        background.save(encoded, format="JPEG", optimize=False, progressive=False, quality=95)
    else:  # pragma: no cover - guarded by _normalize_formats
        raise LogoDerivativeError(f"unsupported derivative format: {output_format.value}")
    return encoded.getvalue()
