from datetime import datetime, timezone

import pytest

from financial_registry.domain import (
    CandidateRecord,
    Identifier,
    SourceDefinition,
    SourceRun,
    SourceRunStatus,
    SourceType,
    TrustTier,
)
from financial_registry.merge import RegistryAssembler

NOW = datetime(2026, 8, 27, tzinfo=timezone.utc)


def _source(source_id, source_type, jurisdiction):
    return SourceDefinition(
        id=source_id,
        publisher=source_id,
        jurisdiction=jurisdiction,
        source_type=source_type,
        url=f"https://example.test/{source_id}",
        terms_url="https://example.test/terms",
        trust_tier=TrustTier.AUTHORITATIVE,
        check_frequency="daily",
        connector_version="test-1",
    )


def _run(source_id):
    return SourceRun(
        id=f"{source_id}:run-1",
        source_id=source_id,
        started_at=NOW,
        finished_at=NOW,
        status=SourceRunStatus.SUCCEEDED,
        snapshot_path=f"/tmp/{source_id}.bin",
        snapshot_sha256="a" * 64,
        candidate_count=1,
    )


def _candidate(source_id, record_id, name, country, *, lei=None, categories=None, domain=None, regulator_id=None):
    identifiers = []
    if lei:
        identifiers.append(
            Identifier(
                owner_id=f"candidate:{source_id}:{record_id}",
                type="lei",
                value=lei,
                country_code=country,
                source_id=source_id,
            )
        )
    return CandidateRecord(
        source_id=source_id,
        source_record_id=record_id,
        legal_name=name,
        country_code=country,
        regulator_jurisdiction=country,
        regulator_identifier=regulator_id,
        categories=categories or [],
        aliases=[],
        operating_markets=[country],
        identifiers=identifiers,
        domains=[domain] if domain else [],
        source_uri=f"https://example.test/{source_id}/{record_id}",
    )


def test_assembler_merges_by_lei_and_preserves_source_evidence():
    gleif = _source("src_gleif_lei", SourceType.GLEIF, "GLOBAL")
    fdic = _source("src_fdic_bankfind", SourceType.REGULATOR, "US")
    lei = "54930000000000000001"
    candidates = [
        _candidate("src_gleif_lei", lei, "EXAMPLE BANK AG", "DE", lei=lei),
        _candidate(
            "src_fdic_bankfind",
            "14",
            "Example Bank",
            "DE",
            lei=lei,
            categories=["commercial_bank"],
            domain="examplebank.test",
            regulator_id="14",
        ),
    ]

    registry = RegistryAssembler([gleif, fdic], [_run(gleif.id), _run(fdic.id)]).assemble(candidates)

    assert len(registry.institutions) == 1
    institution = registry.institutions[0]
    assert institution.canonical_key == f"institution:lei:{lei}"
    assert institution.legal_name == "EXAMPLE BANK AG"
    assert institution.categories == ["commercial_bank"]
    assert institution.source_ids == ["src_fdic_bankfind", "src_gleif_lei"]
    assert institution.domains == ["examplebank.test"]
    assert {identifier.type for identifier in registry.identifiers} == {"lei"}
    assert {identifier.source_id for identifier in registry.identifiers} == {"src_fdic_bankfind", "src_gleif_lei"}
    assert {identifier.owner_id for identifier in registry.identifiers} == {institution.id}


def test_assembler_does_not_guess_matches_for_records_without_lei():
    fdic = _source("src_fdic_bankfind", SourceType.REGULATOR, "US")
    candidates = [
        _candidate("src_fdic_bankfind", "100", "First Bank", "US", categories=["commercial_bank"]),
        _candidate("src_fdic_bankfind", "101", "Second Bank", "US", categories=["commercial_bank"]),
    ]

    registry = RegistryAssembler([fdic], [_run(fdic.id)]).assemble(candidates)

    assert len(registry.institutions) == 2
    assert sorted(item.canonical_key for item in registry.institutions) == [
        "institution:source:src_fdic_bankfind:100",
        "institution:source:src_fdic_bankfind:101",
    ]


def test_assembler_prefers_regulator_country_and_reports_conflict():
    gleif = _source("src_gleif_lei", SourceType.GLEIF, "GLOBAL")
    fdic = _source("src_fdic_bankfind", SourceType.REGULATOR, "US")
    lei = "54930000000000000001"
    candidates = [
        _candidate("src_gleif_lei", lei, "EXAMPLE BANK AG", "DE", lei=lei),
        _candidate("src_fdic_bankfind", "14", "EXAMPLE BANK AG", "US", lei=lei, categories=["commercial_bank"]),
    ]

    result = RegistryAssembler([gleif, fdic], [_run(gleif.id), _run(fdic.id)]).assemble_with_report(candidates)

    assert result.registry.institutions[0].country_code == "US"
    assert len(result.conflicts) == 1
    assert result.conflicts[0].field_kind == "country_code"
    assert result.conflicts[0].winner_source_id == "src_fdic_bankfind"
    assert result.conflicts[0].losing_source_id == "src_gleif_lei"


def test_assembler_ignores_case_only_name_variation():
    gleif = _source("src_gleif_lei", SourceType.GLEIF, "GLOBAL")
    fdic = _source("src_fdic_bankfind", SourceType.REGULATOR, "US")
    lei = "54930000000000000001"
    result = RegistryAssembler([gleif, fdic], [_run(gleif.id), _run(fdic.id)]).assemble_with_report(
        [
            _candidate("src_gleif_lei", lei, "EXAMPLE BANK AG", "DE", lei=lei),
            _candidate("src_fdic_bankfind", "14", "Example Bank AG", "DE", lei=lei),
        ]
    )

    assert result.conflicts == ()


def test_assembler_rejects_candidates_without_a_successful_source_run():
    fdic = _source("src_fdic_bankfind", SourceType.REGULATOR, "US")
    failed_run = _run(fdic.id).model_copy(update={"status": SourceRunStatus.FAILED})

    with pytest.raises(ValueError, match="successful source run"):
        RegistryAssembler([fdic], [failed_run]).assemble(
            [_candidate("src_fdic_bankfind", "100", "First Bank", "US")]
        )
