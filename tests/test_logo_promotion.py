from __future__ import annotations

from datetime import datetime, timezone

import pytest

from financial_registry.assets import AssetProcessor
from financial_registry.domain import (
    AssetCandidate,
    Institution,
    RegistryInput,
    RightsStatus,
    SourceDefinition,
    SourceType,
    TrustTier,
)
from financial_registry.fetch_policy import FetchedAsset
from financial_registry.logo_promotion import LogoReviewDecision, promote_reviewed_logos

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


def _source() -> SourceDefinition:
    return SourceDefinition(
        id="src_demo",
        publisher="Demo source",
        jurisdiction="US",
        source_type=SourceType.OFFICIAL_DOMAIN,
        url="https://example.test/source",
        terms_url="https://example.test/terms",
        trust_tier=TrustTier.OFFICIAL,
        check_frequency="daily",
        connector_version="test-1",
    )


def _candidate() -> AssetCandidate:
    return AssetCandidate(
        id="asset_logo_candidate",
        owner_id="inst_demo",
        variant="primary",
        source_id="src_demo",
        source_uri="https://example.test/logo.svg",
        rights_status=RightsStatus.SOURCE_LINK_ONLY,
        rights_note="discovered from official domain",
    )


def _registry(tmp_path) -> RegistryInput:
    return RegistryInput(
        institutions=[
            Institution(
                id="inst_demo",
                canonical_key="institution:test:demo",
                legal_name="Demo Bank",
                normalized_name="demo bank",
                country_code="US",
                regulator_jurisdiction="US",
            )
        ],
        sources=[_source()],
        asset_root=str(tmp_path),
    )


def _decision(**overrides) -> LogoReviewDecision:
    values = {
        "candidate_id": "asset_logo_candidate",
        "review_status": "approved",
        "rights_status": "redistributable",
        "license_name": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "reviewed_by": "reviewer@example.test",
        "reviewed_at": NOW,
    }
    values.update(overrides)
    return LogoReviewDecision.model_validate(values)


class FakeFetcher:
    def __init__(self, body: bytes, content_type: str = "image/svg+xml"):
        self.body = body
        self.content_type = content_type
        self.calls: list[str] = []

    def fetch(self, url: str) -> FetchedAsset:
        self.calls.append(url)
        return FetchedAsset(url=url, final_url=url, body=self.body, content_type=self.content_type)


def test_promote_approved_binary_candidate_sanitizes_and_stages_asset(tmp_path):
    fetcher = FakeFetcher(
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script><rect width="4" height="4"/></svg>'
    )
    registry = _registry(tmp_path)

    result = promote_reviewed_logos(
        registry,
        [_candidate()],
        [_decision()],
        fetcher=fetcher,
        processor=AssetProcessor(url_validator=lambda url: url),
        clock=lambda: NOW,
    )

    assert fetcher.calls == ["https://example.test/logo.svg"]
    assert len(result.registry.assets) == 1
    asset = result.registry.assets[0]
    assert asset.binary_path == "assets/asset_logo_candidate.svg"
    assert asset.staging_path == "logos/asset_logo_candidate.svg"
    assert asset.sha256 and len(asset.sha256) == 64
    assert b"script" not in (tmp_path / asset.staging_path).read_bytes()
    assert asset.reviewed_by == "reviewer@example.test"
    assert asset.verified_at == NOW


def test_promote_source_link_only_approval_does_not_fetch_or_write_binary(tmp_path):
    class NoFetch:
        def fetch(self, url: str):
            raise AssertionError("source_link_only approval must not fetch")

    registry = _registry(tmp_path)
    result = promote_reviewed_logos(
        registry,
        [_candidate()],
        [_decision(rights_status="source_link_only", license_name=None, license_url=None)],
        fetcher=NoFetch(),
        processor=AssetProcessor(url_validator=lambda url: url),
        clock=lambda: NOW,
    )

    asset = result.registry.assets[0]
    assert asset.rights_status is RightsStatus.SOURCE_LINK_ONLY
    assert asset.binary_path is None
    assert asset.sha256 is None
    assert asset.staging_path is None
    assert asset.format.value == "svg"


def test_promote_nominative_use_candidate_fetches_and_stages_binary(tmp_path):
    fetcher = FakeFetcher(b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="4" height="4"/></svg>')
    registry = _registry(tmp_path)

    result = promote_reviewed_logos(
        registry,
        [_candidate()],
        [_decision(
            rights_status="nominative_use",
            license_name=None,
            license_url=None,
            rights_note="Upstream nominative-use policy; identification only, no endorsement.",
        )],
        fetcher=fetcher,
        processor=AssetProcessor(url_validator=lambda url: url),
        clock=lambda: NOW,
    )

    asset = result.registry.assets[0]
    assert asset.rights_status is RightsStatus.NOMINATIVE_USE
    assert asset.rights_note == "Upstream nominative-use policy; identification only, no endorsement."
    assert asset.binary_path == "assets/asset_logo_candidate.svg"
    assert (tmp_path / asset.staging_path).exists()


def test_promote_rejects_decisions_for_unknown_candidates(tmp_path):
    registry = _registry(tmp_path)

    with pytest.raises(ValueError, match="unknown logo candidate"):
        promote_reviewed_logos(
            registry,
            [_candidate()],
            [_decision(candidate_id="missing")],
            fetcher=FakeFetcher(b"unused"),
            processor=AssetProcessor(url_validator=lambda url: url),
            clock=lambda: NOW,
        )


def test_promote_rejects_path_unsafe_candidate_ids(tmp_path):
    candidate = _candidate().model_copy(update={"id": "../escape"})

    with pytest.raises(ValueError, match="stable path-safe"):
        promote_reviewed_logos(
            _registry(tmp_path),
            [candidate],
            [_decision(candidate_id="../escape")],
            fetcher=FakeFetcher(b"unused"),
            processor=AssetProcessor(url_validator=lambda url: url),
            clock=lambda: NOW,
        )
