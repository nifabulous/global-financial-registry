from datetime import datetime, timezone

import pytest

from financial_registry.domain import AssetCandidate, Institution, ReviewStatus, RightsStatus
from financial_registry.logo_discovery import (
    LogoRightsReviewer,
    OfficialDomainLogoDiscovery,
    RightsReviewError,
)


def _institution(*domains: str) -> Institution:
    return Institution(
        id="inst_acme",
        canonical_key="institution:lei:549300ACME0000000000",
        legal_name="Acme Bank plc",
        normalized_name="acme bank plc",
        country_code="US",
        regulator_jurisdiction="US",
        domains=list(domains),
    )


def _candidate() -> AssetCandidate:
    return AssetCandidate(
        id="asset_logo_candidate",
        owner_id="inst_acme",
        variant="primary",
        source_id="src_official_domain_logo",
        source_uri="https://acme.example/logo.svg",
        rights_status=RightsStatus.SOURCE_LINK_ONLY,
        rights_note="discovered from official domain",
    )


def test_discovery_generates_deterministic_rights_safe_candidates():
    discovery = OfficialDomainLogoDiscovery(
        source_id="src_official_domain_logo",
        paths=("/logo.svg", "/favicon.ico"),
    )

    candidates = discovery.discover([_institution("https://WWW.Acme.example/", "acme.example", "")])

    assert [candidate.source_uri for candidate in candidates] == [
        "https://acme.example/logo.svg",
        "https://acme.example/favicon.ico",
    ]
    assert len({candidate.id for candidate in candidates}) == 2
    assert all(candidate.owner_id == "inst_acme" for candidate in candidates)
    assert all(candidate.rights_status is RightsStatus.SOURCE_LINK_ONLY for candidate in candidates)
    assert all(candidate.review_status is ReviewStatus.CANDIDATE for candidate in candidates)
    assert all(candidate.discovery_method == "official_domain_path" for candidate in candidates)
    assert all(candidate.rights_note for candidate in candidates)


def test_discovery_is_stable_for_multiple_institutions_and_skips_missing_domains():
    discovery = OfficialDomainLogoDiscovery(source_id="src_official_domain_logo", paths=("/logo.svg",))

    first = discovery.discover([_institution("bank.example"), _institution()])
    second = discovery.discover([_institution("bank.example"), _institution()])

    assert [(item.id, item.source_uri) for item in first] == [(item.id, item.source_uri) for item in second]
    assert len(first) == 1


def test_html_discovery_extracts_same_site_icons_and_social_images():
    html = """
    <html><head>
      <link rel="icon" type="image/svg+xml" href="/assets/favicon.svg">
      <link rel="apple-touch-icon" href="https://cdn.acme.example/app-icon.png">
      <meta property="og:image" content="/brand/og.png">
      <meta name="twitter:image" content="https://evil.example/logo.png">
    </head></html>
    """

    candidates = OfficialDomainLogoDiscovery().discover_html(
        _institution("acme.example"),
        "https://www.acme.example/about",
        html,
    )

    assert [candidate.source_uri for candidate in candidates] == [
        "https://acme.example/assets/favicon.svg",
        "https://cdn.acme.example/app-icon.png",
        "https://acme.example/brand/og.png",
    ]
    assert [candidate.discovery_method for candidate in candidates] == [
        "official_html_link",
        "official_html_link",
        "official_html_meta",
    ]
    assert all(candidate.rights_status is RightsStatus.SOURCE_LINK_ONLY for candidate in candidates)


def test_html_discovery_deduplicates_urls_and_strips_fragments():
    html = """
    <link rel="icon" href="/logo.svg#primary">
    <link rel="shortcut icon" href="https://acme.example/logo.svg">
    <meta property="og:image" content="/logo.svg#social">
    """

    candidates = OfficialDomainLogoDiscovery().discover_html(
        _institution("acme.example"),
        "https://acme.example/",
        html,
    )

    assert len(candidates) == 1
    assert candidates[0].source_uri == "https://acme.example/logo.svg"
    assert candidates[0].confidence == 0.9


def test_html_discovery_skips_unsafe_or_unrelated_links():
    html = """
    <link rel="icon" href="javascript:alert(1)">
    <link rel="icon" href="data:image/svg+xml;base64,abc">
    <meta property="og:image" content="http://acme.example/insecure.png">
    <meta property="og:image" content="https://unrelated.example/logo.png">
    """

    candidates = OfficialDomainLogoDiscovery().discover_html(
        _institution("acme.example"),
        "https://acme.example/",
        html,
    )

    assert candidates == []


def test_html_discovery_ignores_pages_outside_institution_domains():
    candidates = OfficialDomainLogoDiscovery().discover_html(
        _institution("acme.example"),
        "https://unrelated.example/",
        '<link rel="icon" href="/logo.svg">',
    )

    assert candidates == []


def test_redistributable_approval_requires_rights_evidence():
    reviewer = LogoRightsReviewer()

    with pytest.raises(RightsReviewError, match="license URL or permission reference"):
        reviewer.review(
            _candidate(),
            decision=ReviewStatus.APPROVED,
            rights_status=RightsStatus.REDISTRIBUTABLE,
        )


def test_licensed_approval_requires_permission_and_territories():
    reviewer = LogoRightsReviewer()

    with pytest.raises(RightsReviewError, match="permission_reference"):
        reviewer.review(
            _candidate(),
            decision=ReviewStatus.APPROVED,
            rights_status=RightsStatus.LICENSED,
            license_name="Permission",
            license_url="https://acme.example/brand-terms",
        )

    with pytest.raises(RightsReviewError, match="territor"):
        reviewer.review(
            _candidate(),
            decision=ReviewStatus.APPROVED,
            rights_status=RightsStatus.LICENSED,
            license_name="Permission",
            license_url="https://acme.example/brand-terms",
            permission_reference="ticket-123",
        )


def test_source_link_only_review_can_be_approved_for_link_publication_only():
    reviewed = LogoRightsReviewer().review(
        _candidate(),
        decision=ReviewStatus.APPROVED,
        rights_status=RightsStatus.SOURCE_LINK_ONLY,
        rights_note="Official-domain link retained; redistribution permission not established.",
        reviewed_by="reviewer@example.test",
        reviewed_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
    )

    assert reviewed.review_status is ReviewStatus.APPROVED
    assert reviewed.rights_status is RightsStatus.SOURCE_LINK_ONLY
    assert reviewed.permission_reference is None
    assert LogoRightsReviewer.can_publish_binary(reviewed) is False


def test_approved_redistributable_candidate_is_publishable():
    reviewed = LogoRightsReviewer().review(
        _candidate(),
        decision=ReviewStatus.APPROVED,
        rights_status=RightsStatus.REDISTRIBUTABLE,
        license_name="CC BY 4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
    )

    assert reviewed.rights_status is RightsStatus.REDISTRIBUTABLE
    assert reviewed.rights_note == _candidate().rights_note
    assert LogoRightsReviewer.can_publish_binary(reviewed) is True


def test_review_accepts_serialized_enum_values():
    with pytest.raises(RightsReviewError, match="license URL or permission reference"):
        LogoRightsReviewer().review(
            _candidate(),
            decision="approved",
            rights_status="redistributable",
        )

    reviewed = LogoRightsReviewer().review(
        _candidate(),
        decision="approved",
        rights_status="source_link_only",
    )

    assert reviewed.review_status is ReviewStatus.APPROVED
    assert reviewed.rights_status is RightsStatus.SOURCE_LINK_ONLY


def test_review_materializes_territory_iterables_once():
    reviewed = LogoRightsReviewer().review(
        _candidate(),
        decision=ReviewStatus.APPROVED,
        rights_status=RightsStatus.LICENSED,
        permission_reference="ticket-123",
        territories=iter(["US"]),
    )

    assert reviewed.territories == ["US"]
