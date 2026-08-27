import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from financial_registry.connectors.gleif import GLEIFConnector
from financial_registry.snapshots import FilesystemSnapshotStore


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, *, params):
        self.calls.append((url, params.copy()))
        return next(self.responses)


def _record(
    lei,
    name,
    country="DE",
    *,
    bic=None,
    registered_as=None,
    other_names=None,
    jurisdiction=None,
):
    return {
        "type": "lei-records",
        "id": lei,
        "attributes": {
            "lei": lei,
            "entity": {
                "legalName": {"name": name, "language": "en"},
                "otherNames": other_names or [],
                "transliteratedOtherNames": [],
                "legalAddress": {"country": country},
                "headquartersAddress": {"country": country},
                "jurisdiction": jurisdiction or country,
                "registeredAs": registered_as,
                "status": "ACTIVE",
            },
            "bic": bic,
        },
        "links": {"self": f"https://api.gleif.org/api/v1/lei-records/{lei}"},
    }


def _page(records, page, last_page):
    return {
        "meta": {"pagination": {"currentPage": page, "lastPage": last_page}},
        "data": records,
    }


def test_fetch_paginates_and_stores_replayable_snapshot(tmp_path):
    first = _record("54930000000000000001", "Example Bank AG")
    second = _record("54930000000000000002", "Second Bank AG")
    client = _FakeClient([_FakeResponse(_page([first], 1, 2)), _FakeResponse(_page([second], 2, 2))])
    store = FilesystemSnapshotStore(tmp_path / "snapshots")
    retrieved_at = datetime(2026, 8, 27, tzinfo=timezone.utc)
    connector = GLEIFConnector(
        store,
        client=client,
        page_size=1,
        max_records=None,
        clock=lambda: retrieved_at,
    )

    snapshot = connector.fetch()

    assert connector.definition.id == "src_gleif_lei"
    assert snapshot.source_id == connector.definition.id
    assert snapshot.retrieved_at == retrieved_at
    payload = json.loads(store.read(snapshot))
    assert [record["id"] for page in payload["pages"] for record in page["data"]] == [
        "54930000000000000001",
        "54930000000000000002",
    ]
    assert [call[1]["page[number]"] for call in client.calls] == [1, 2]
    assert all(call[1]["page[size]"] == 1 for call in client.calls)


def test_fetch_respects_max_records_without_fetching_unneeded_pages(tmp_path):
    records = [_record(f"5493000000000000000{i}", f"Bank {i}") for i in range(1, 5)]
    client = _FakeClient([_FakeResponse(_page(records[:2], 1, 2)), _FakeResponse(_page(records[2:], 2, 2))])
    connector = GLEIFConnector(
        FilesystemSnapshotStore(tmp_path / "snapshots"),
        client=client,
        page_size=2,
        max_records=3,
    )

    snapshot = connector.fetch()
    candidates = connector.normalize(snapshot)

    assert len(candidates) == 3
    assert len(client.calls) == 2
    assert [candidate.source_record_id for candidate in candidates] == [
        "54930000000000000001",
        "54930000000000000002",
        "54930000000000000003",
    ]


def test_normalize_maps_identity_aliases_and_identifiers(tmp_path):
    lei = "54930000000000000001"
    record = _record(
        lei,
        "Example Bank Aktiengesellschaft",
        bic=["EXAMPLEDXXX", "EXAMPLE2XXX"],
        registered_as="HRB 12345",
        other_names=[{"name": "Example Bank", "type": "PREVIOUS_LEGAL_NAME"}],
    )
    client = _FakeClient([_FakeResponse(_page([record], 1, 1))])
    connector = GLEIFConnector(FilesystemSnapshotStore(tmp_path / "snapshots"), client=client)

    candidates = connector.normalize(connector.fetch())

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source_record_id == lei
    assert candidate.legal_name == "Example Bank Aktiengesellschaft"
    assert candidate.country_code == "DE"
    assert candidate.regulator_jurisdiction == "DE"
    assert candidate.aliases == ["Example Bank"]
    assert candidate.source_uri.endswith(f"/{lei}")
    assert {(identifier.type, identifier.value) for identifier in candidate.identifiers} == {
        ("lei", lei),
        ("bic", "EXAMPLEDXXX"),
        ("bic", "EXAMPLE2XXX"),
        ("national_registration", "HRB 12345"),
    }
    assert {identifier.owner_id for identifier in candidate.identifiers} == {f"candidate:src_gleif_lei:{lei}"}


def test_fetch_rejects_malformed_api_payload(tmp_path):
    client = _FakeClient([_FakeResponse({"meta": {"pagination": {"lastPage": 1}}})])
    connector = GLEIFConnector(FilesystemSnapshotStore(tmp_path / "snapshots"), client=client)

    with pytest.raises(ValueError, match="data must be a list"):
        connector.fetch()


def test_normalize_rejects_a_tampered_snapshot(tmp_path):
    record = _record("54930000000000000001", "Example Bank AG")
    store = FilesystemSnapshotStore(tmp_path / "snapshots")
    connector = GLEIFConnector(store, client=_FakeClient([_FakeResponse(_page([record], 1, 1))]))
    snapshot = connector.fetch()
    Path(snapshot.path).write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="checksum mismatch"):
        connector.normalize(snapshot)
