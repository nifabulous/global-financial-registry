"""Discover and review logo links without assuming redistribution rights.

Logo discovery is intentionally metadata-only. An institution's official domain is
useful evidence for finding a candidate asset, but it is not permission to copy,
store, or redistribute the asset. Candidates therefore start as
``source_link_only`` and must pass an explicit rights review before a binary is
eligible for publication.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from ipaddress import ip_address
from typing import Callable

from .domain import AssetCandidate, AssetVariant, Institution, ReviewStatus, RightsStatus
from .ids import StableIdAllocator
from .normalize import normalize_domain


class RightsReviewError(ValueError):
    """Raised when a logo review does not contain sufficient rights evidence."""


class OfficialDomainLogoDiscovery:
    """Generate deterministic logo URL candidates from institution domains.

    The class never performs network requests. It only creates source links that
    a later, policy-controlled fetch step may inspect. Keeping discovery and
    fetching separate prevents an unreviewed logo from becoming a public binary.
    """

    DEFAULT_PATHS = ("/logo.svg", "/favicon.svg", "/favicon.ico")

    def __init__(
        self,
        source_id: str = "src_official_domain_logo",
        paths: Iterable[str] = DEFAULT_PATHS,
        id_allocator: StableIdAllocator | None = None,
    ):
        self.source_id = source_id
        self.paths = tuple(self._validate_path(path) for path in paths)
        if not self.paths:
            raise ValueError("at least one logo discovery path is required")
        self.id_allocator = id_allocator or StableIdAllocator()

    @staticmethod
    def _validate_path(path: str) -> str:
        if not isinstance(path, str):
            raise TypeError("logo discovery paths must be strings")
        normalized = path.strip()
        if not normalized.startswith("/") or "://" in normalized or any(char.isspace() for char in normalized):
            raise ValueError("logo discovery paths must be absolute local paths")
        return normalized

    @staticmethod
    def _is_public_hostname(hostname: str) -> bool:
        if "." not in hostname or "/" in hostname or ":" in hostname:
            return False
        try:
            ip_address(hostname)
        except ValueError:
            return True
        return False

    @staticmethod
    def _confidence(path: str) -> float:
        if path.casefold().endswith("/logo.svg"):
            return 0.75
        if path.casefold().endswith("/favicon.svg"):
            return 0.65
        if path.casefold().endswith("/favicon.ico"):
            return 0.55
        return 0.5

    def discover(self, institutions: Iterable[Institution]) -> list[AssetCandidate]:
        """Return stable, source-link-only candidates for verified domain fields."""

        candidates: list[AssetCandidate] = []
        seen: set[tuple[str, str, str]] = set()
        ordered_institutions = sorted(institutions, key=lambda item: (item.id, item.canonical_key))
        for institution in ordered_institutions:
            domains = sorted({normalize_domain(value) for value in institution.domains if value})
            for domain in domains:
                if not self._is_public_hostname(domain):
                    continue
                for path in self.paths:
                    key = (institution.id, domain, path)
                    if key in seen:
                        continue
                    seen.add(key)
                    canonical_key = f"logo:{institution.id}:{domain}{path}"
                    candidates.append(
                        AssetCandidate(
                            id=self.id_allocator.allocate("asset", canonical_key),
                            owner_id=institution.id,
                            variant=AssetVariant.PRIMARY,
                            source_id=self.source_id,
                            source_uri=f"https://{domain}{path}",
                            rights_status=RightsStatus.SOURCE_LINK_ONLY,
                            review_status=ReviewStatus.CANDIDATE,
                            discovery_method="official_domain_path",
                            confidence=self._confidence(path),
                            rights_note=(
                                "Official-domain candidate; visibility on the domain does not establish "
                                "redistribution permission."
                            ),
                        )
                    )
        return candidates


class LogoRightsReviewer:
    """Apply an explicit rights decision to a discovered logo candidate."""

    def __init__(self, clock: Callable[[], datetime] | None = None):
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def review(
        self,
        candidate: AssetCandidate,
        *,
        decision: ReviewStatus | str,
        rights_status: RightsStatus | str,
        license_name: str | None = None,
        license_url: str | None = None,
        permission_reference: str | None = None,
        territories: Iterable[str] | None = None,
        expires_at: datetime | None = None,
        rights_note: str | None = None,
        attribution_text: str | None = None,
        reviewed_by: str | None = None,
        reviewed_at: datetime | None = None,
    ) -> AssetCandidate:
        decision = ReviewStatus(decision)
        rights_status = RightsStatus(rights_status)
        territory_values = list(territories) if territories is not None else []
        if decision is ReviewStatus.APPROVED:
            self._require_approval_evidence(
                rights_status=rights_status,
                license_url=license_url,
                permission_reference=permission_reference,
                territories=territory_values,
            )

        values = candidate.model_dump(mode="python")
        values.update(
            {
                "rights_status": rights_status,
                "review_status": decision,
                "license_name": license_name,
                "license_url": license_url,
                "permission_reference": permission_reference,
                "territories": territory_values,
                "expires_at": expires_at,
                "rights_note": rights_note if rights_note is not None else candidate.rights_note,
                "attribution_text": attribution_text if attribution_text is not None else candidate.attribution_text,
                "reviewed_by": reviewed_by,
                "reviewed_at": reviewed_at or self.clock(),
            }
        )
        return AssetCandidate.model_validate(values)

    @staticmethod
    def _require_approval_evidence(
        *,
        rights_status: RightsStatus,
        license_url: str | None,
        permission_reference: str | None,
        territories: Iterable[str] | None,
    ) -> None:
        if rights_status in {RightsStatus.UNKNOWN, RightsStatus.REMOVED}:
            raise RightsReviewError("unknown or removed rights cannot be approved")
        if rights_status is RightsStatus.REDISTRIBUTABLE and not (license_url or permission_reference):
            raise RightsReviewError("redistributable approval requires a license URL or permission reference")
        if rights_status is RightsStatus.LICENSED:
            if not permission_reference:
                raise RightsReviewError("licensed approval requires permission_reference")
            if not list(territories or []):
                raise RightsReviewError("licensed approval requires at least one territory")

    @staticmethod
    def can_publish_binary(candidate: AssetCandidate, now: datetime | None = None) -> bool:
        """Return whether a candidate is eligible for a public binary fetch."""

        if candidate.review_status is not ReviewStatus.APPROVED:
            return False
        if candidate.rights_status is RightsStatus.REDISTRIBUTABLE:
            return bool(candidate.license_url or candidate.permission_reference)
        if candidate.rights_status is RightsStatus.LICENSED:
            if not candidate.permission_reference or not candidate.territories:
                return False
            reference_time = now or datetime.now(timezone.utc)
            return candidate.expires_at is None or candidate.expires_at > reference_time
        return False


__all__ = ["LogoRightsReviewer", "OfficialDomainLogoDiscovery", "RightsReviewError"]
