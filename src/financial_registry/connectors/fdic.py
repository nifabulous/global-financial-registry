from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from ..domain import CandidateRecord, Identifier, SourceDefinition, SourceType, TrustTier
from ..normalize import normalize_domain, normalize_identifier
from ..snapshots import FilesystemSnapshotStore, RawSnapshot

_FDIC_CLASS_TO_CATEGORY = {
    "N": "commercial_bank",
    "NM": "commercial_bank",
    "SM": "commercial_bank",
    "SB": "savings_bank",
    "SI": "savings_bank",
    "SA": "savings_association",
    "SL": "savings_association",
    "OI": "foreign_branch",
    "CU": "credit_union",
}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


class FDICConnector:
    """Fetch and normalize FDIC BankFind institution records."""

    endpoint = "https://api.fdic.gov/banks/institutions"
    default_fields = (
        "ID",
        "NAME",
        "CERT",
        "LEI",
        "STALP",
        "ACTIVE",
        "BKCLASS",
        "WEBADDR",
        "REGAGNT",
    )

    def __init__(
        self,
        snapshot_store: FilesystemSnapshotStore,
        *,
        client: Any | None = None,
        page_size: int = 1_000,
        max_records: int | None = 1_000,
        filters: str | None = None,
        fields: tuple[str, ...] | None = None,
        clock: Callable[[], datetime] | None = None,
        api_key: str | None = None,
    ):
        if page_size < 1 or page_size > 10_000:
            raise ValueError("page_size must be between 1 and 10000")
        if max_records is not None and max_records < 1:
            raise ValueError("max_records must be positive or None")
        self.snapshot_store = snapshot_store
        self.client = client or httpx.Client(timeout=30.0, follow_redirects=True)
        self.page_size = page_size
        self.max_records = max_records
        self.filters = "ACTIVE:1" if filters is None else filters
        self.fields = tuple(fields or self.default_fields)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.api_key = api_key
        self.definition = SourceDefinition(
            id="src_fdic_bankfind",
            publisher="Federal Deposit Insurance Corporation",
            jurisdiction="US",
            source_type=SourceType.REGULATOR,
            url=self.endpoint,
            terms_url="https://fdic.gov/resources/data-tools",
            trust_tier=TrustTier.AUTHORITATIVE,
            check_frequency="daily",
            connector_version="fdic-bankfind-v1",
        )

    def _params(self, offset: int) -> dict[str, int | str]:
        params: dict[str, int | str] = {
            "fields": ",".join(self.fields),
            "filters": self.filters,
            "limit": self.page_size,
            "offset": offset,
            "sort_by": "CERT",
            "sort_order": "ASC",
        }
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    @staticmethod
    def _validate_payload(payload: Any) -> tuple[list[dict[str, Any]], int]:
        if not isinstance(payload, Mapping):
            raise ValueError("FDIC response must be an object")
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError("FDIC response data must be a list")
        if not all(isinstance(record, Mapping) for record in data):
            raise ValueError("FDIC response data records must be objects")
        meta = payload.get("meta")
        if not isinstance(meta, Mapping):
            raise ValueError("FDIC response meta must be an object")
        total = meta.get("total")
        if not isinstance(total, int) or total < 0:
            raise ValueError("FDIC response meta.total must be a non-negative integer")
        return list(data), total

    def fetch(self) -> RawSnapshot:
        pages: list[dict[str, Any]] = []
        offset = 0
        record_count = 0

        while True:
            response = self.client.get(self.endpoint, params=self._params(offset))
            response.raise_for_status()
            data, total = self._validate_payload(response.json())

            if self.max_records is not None:
                remaining = self.max_records - record_count
                page_data = data[:remaining]
            else:
                page_data = data
            pages.append({"offset": offset, "data": page_data, "total": total})
            record_count += len(page_data)

            if not data or offset + len(data) >= total:
                break
            if self.max_records is not None and record_count >= self.max_records:
                break
            offset += len(data)

        document = {
            "endpoint": self.endpoint,
            "fields": self.fields,
            "filters": self.filters,
            "page_size": self.page_size,
            "max_records": self.max_records,
            "pages": pages,
        }
        body = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return self.snapshot_store.put(self.definition.id, self.clock(), body)

    def normalize(self, snapshot: RawSnapshot) -> list[CandidateRecord]:
        if snapshot.source_id != self.definition.id:
            raise ValueError(f"FDIC snapshot source mismatch: {snapshot.source_id}")
        document = json.loads(self.snapshot_store.read(snapshot))
        pages = document.get("pages") if isinstance(document, Mapping) else None
        if not isinstance(pages, list):
            raise ValueError("FDIC snapshot pages must be a list")

        candidates: list[CandidateRecord] = []
        for page in pages:
            if not isinstance(page, Mapping) or not isinstance(page.get("data"), list):
                raise ValueError("FDIC snapshot page data must be a list")
            for record in page["data"]:
                candidates.append(self._normalize_record(record))
        return candidates

    def _normalize_record(self, record: Any) -> CandidateRecord:
        if not isinstance(record, Mapping):
            raise ValueError("FDIC record must be an object")
        row = record.get("data", record)
        if not isinstance(row, Mapping):
            raise ValueError("FDIC record data must be an object")

        record_id = _text(row.get("ID")) or _text(row.get("UNINUM")) or _text(row.get("CERT"))
        legal_name = _text(row.get("NAME"))
        if not record_id:
            raise ValueError("FDIC record is missing an ID")
        if not legal_name:
            raise ValueError(f"FDIC record {record_id} is missing a name")

        candidate_owner = f"candidate:{self.definition.id}:{record_id}"
        identifiers: list[Identifier] = []
        fdic_id = _text(row.get("ID"))
        if fdic_id:
            identifiers.append(
                Identifier(
                    owner_id=candidate_owner,
                    type="fdic_id",
                    value=fdic_id,
                    country_code="US",
                    source_id=self.definition.id,
                )
            )
        certificate = _text(row.get("CERT"))
        if certificate:
            identifiers.append(
                Identifier(
                    owner_id=candidate_owner,
                    type="fdic_cert",
                    value=certificate,
                    country_code="US",
                    source_id=self.definition.id,
                )
            )
        lei = _text(row.get("LEI"))
        if lei:
            identifiers.append(
                Identifier(
                    owner_id=candidate_owner,
                    type="lei",
                    value=normalize_identifier("lei", lei),
                    country_code="US",
                    source_id=self.definition.id,
                )
            )

        domain = normalize_domain(_text(row.get("WEBADDR")) or "")
        source_query = urlencode({"filters": f"ID:{record_id}"})
        bank_class = (_text(row.get("BKCLASS")) or "").upper()
        category = _FDIC_CLASS_TO_CATEGORY.get(bank_class, "fdic_institution")
        return CandidateRecord(
            source_id=self.definition.id,
            source_record_id=record_id,
            legal_name=legal_name,
            country_code="US",
            regulator_jurisdiction="US",
            regulator_identifier=certificate or record_id,
            categories=[category],
            operating_markets=["US"],
            identifiers=identifiers,
            domains=[domain] if domain else [],
            source_uri=f"{self.endpoint}?{source_query}",
        )
