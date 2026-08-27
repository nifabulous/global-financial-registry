from datetime import datetime, timezone

from financial_registry.domain import (
    CandidateRecord,
    Identifier,
    SourceDefinition,
    SourceType,
    TrustTier,
)
from financial_registry.pilot import run_registry_pilot
from financial_registry.snapshots import FilesystemSnapshotStore

NOW = datetime(2026, 8, 27, tzinfo=timezone.utc)


def _source(source_id: str, source_type: SourceType, jurisdiction: str) -> SourceDefinition:
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


def _candidate(source_id: str, record_id: str, lei: str) -> CandidateRecord:
    return CandidateRecord(
        source_id=source_id,
        source_record_id=record_id,
        legal_name="Example Bank",
        country_code="US",
        regulator_jurisdiction="US",
        identifiers=[
            Identifier(
                owner_id=f"candidate:{source_id}:{record_id}",
                type="lei",
                value=lei,
                country_code="US",
                source_id=source_id,
            )
        ],
    )


class FakeConnector:
    def __init__(self, source, candidate, store):
        self.definition = source
        self.candidate = candidate
        self.store = store

    def fetch(self):
        return self.store.put(self.definition.id, NOW, self.definition.id.encode())

    def normalize(self, snapshot):
        return [self.candidate]


class FailingConnector:
    def __init__(self, source):
        self.definition = source
        self.max_records = 1

    def fetch(self):
        raise RuntimeError("source unavailable")

    def normalize(self, snapshot):
        raise AssertionError("normalize must not run after fetch failure")


def test_run_registry_pilot_merges_normalized_candidates_deterministically(tmp_path):
    store = FilesystemSnapshotStore(tmp_path / "snapshots")
    lei = "54930000000000000001"
    gleif = _source("src_gleif_lei", SourceType.GLEIF, "GLOBAL")
    regulator = _source("src_regulator_us", SourceType.REGULATOR, "US")
    connectors = [
        FakeConnector(regulator, _candidate(regulator.id, "us-1", lei), store),
        FakeConnector(gleif, _candidate(gleif.id, "gleif-1", lei), store),
    ]

    result = run_registry_pilot(connectors, now=NOW)

    assert [item.source_run.source_id for item in result.connector_results] == [
        "src_gleif_lei",
        "src_regulator_us",
    ]
    assert result.report.candidate_count == 2
    assert result.report.institution_count == 1
    assert len(result.registry.institutions) == 1
    assert result.registry.institutions[0].canonical_key == f"institution:lei:{lei}"
    assert all(item.candidates for item in result.connector_results)
    assert result.warnings == ()


def test_run_registry_pilot_keeps_successful_sources_when_one_fails(tmp_path):
    store = FilesystemSnapshotStore(tmp_path / "snapshots")
    successful = _source("src_success", SourceType.REGULATOR, "US")
    failed = _source("src_failed", SourceType.REGULATOR, "CA")
    connector = FakeConnector(successful, _candidate(successful.id, "success-1", "54930000000000000001"), store)

    result = run_registry_pilot([FailingConnector(failed), connector], now=NOW)

    assert len(result.registry.institutions) == 1
    assert [item.status.value for item in result.connector_results] == ["failed", "succeeded"]
    assert result.warnings == ("source unavailable",)
