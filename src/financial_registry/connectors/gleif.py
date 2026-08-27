from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

import httpx

from ..domain import CandidateRecord, Identifier, SourceDefinition, SourceType, TrustTier
from ..normalize import normalize_identifier
from ..snapshots import FilesystemSnapshotStore, RawSnapshot


def _alpha2(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().upper()
    if len(value) != 2 or not value.isascii() or not value.isalpha():
        return None
    return value


def _strings(value: Any) -> list[str]:
    """Extract names or identifier values from GLEIF's string/object/list shapes."""
    if value is None:
        return []
    if isinstance(value, str):
        value = value.strip()
        return [value] if value else []
    if isinstance(value, Mapping):
        for key in ("name", "value", "code"):
            if key in value:
                return _strings(value[key])
        return []
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            values.extend(_strings(item))
        return values
    return []


class GLEIFConnector:
    """Fetch and normalize a bounded, replayable slice of the GLEIF LEI API."""

    endpoint = "https://api.gleif.org/api/v1/lei-records"

    def __init__(
        self,
        snapshot_store: FilesystemSnapshotStore,
        *,
        client: Any | None = None,
        page_size: int = 100,
        max_records: int | None = 1_000,
        filters: Mapping[str, str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        if page_size < 1 or page_size > 100:
            raise ValueError("page_size must be between 1 and 100")
        if max_records is not None and max_records < 1:
            raise ValueError("max_records must be positive or None")
        self.snapshot_store = snapshot_store
        self.client = client or httpx.Client(timeout=30.0, follow_redirects=True)
        self.page_size = page_size
        self.max_records = max_records
        self.filters = dict(sorted((filters or {}).items()))
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.definition = SourceDefinition(
            id="src_gleif_lei",
            publisher="Global Legal Entity Identifier Foundation",
            jurisdiction="GLOBAL",
            source_type=SourceType.GLEIF,
            url=self.endpoint,
            terms_url="https://www.gleif.org/en/lei-data/access-and-use-lei-data",
            trust_tier=TrustTier.AUTHORITATIVE,
            check_frequency="three_times_daily",
            connector_version="gleif-api-v1",
        )

    def _params(self, page_number: int) -> dict[str, int | str]:
        params: dict[str, int | str] = {
            f"filter[{key}]": value for key, value in self.filters.items()
        }
        params["page[number]"] = page_number
        params["page[size]"] = self.page_size
        return params

    @staticmethod
    def _validate_payload(payload: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not isinstance(payload, Mapping):
            raise ValueError("GLEIF response must be an object")
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError("GLEIF response data must be a list")
        if not all(isinstance(record, Mapping) for record in data):
            raise ValueError("GLEIF response data records must be objects")
        meta = payload.get("meta")
        if not isinstance(meta, Mapping):
            raise ValueError("GLEIF response meta must be an object")
        pagination = meta.get("pagination")
        if not isinstance(pagination, Mapping):
            raise ValueError("GLEIF response pagination must be an object")
        last_page = pagination.get("lastPage")
        if not isinstance(last_page, int) or last_page < 1:
            raise ValueError("GLEIF response pagination.lastPage must be a positive integer")
        return list(data), dict(pagination)

    def fetch(self) -> RawSnapshot:
        pages: list[dict[str, Any]] = []
        page_number = 1
        record_count = 0

        while True:
            response = self.client.get(self.endpoint, params=self._params(page_number))
            response.raise_for_status()
            data, pagination = self._validate_payload(response.json())

            if self.max_records is not None:
                remaining = self.max_records - record_count
                page_data = data[:remaining]
            else:
                page_data = data
            pages.append({"number": page_number, "pagination": pagination, "data": page_data})
            record_count += len(page_data)

            last_page = pagination["lastPage"]
            if not data or page_number >= last_page:
                break
            if self.max_records is not None and record_count >= self.max_records:
                break
            page_number += 1

        document = {
            "endpoint": self.endpoint,
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
            raise ValueError(f"GLEIF snapshot source mismatch: {snapshot.source_id}")
        document = json.loads(self.snapshot_store.read(snapshot))
        pages = document.get("pages") if isinstance(document, Mapping) else None
        if not isinstance(pages, list):
            raise ValueError("GLEIF snapshot pages must be a list")

        candidates: list[CandidateRecord] = []
        for page in pages:
            if not isinstance(page, Mapping) or not isinstance(page.get("data"), list):
                raise ValueError("GLEIF snapshot page data must be a list")
            for record in page["data"]:
                candidates.append(self._normalize_record(record))
        return candidates

    def _normalize_record(self, record: Any) -> CandidateRecord:
        if not isinstance(record, Mapping):
            raise ValueError("GLEIF record must be an object")
        attributes = record.get("attributes")
        if not isinstance(attributes, Mapping):
            raise ValueError("GLEIF record attributes must be an object")
        entity = attributes.get("entity")
        if not isinstance(entity, Mapping):
            raise ValueError("GLEIF record entity must be an object")

        record_id = attributes.get("lei") or record.get("id")
        if not isinstance(record_id, str) or not record_id.strip():
            raise ValueError("GLEIF record is missing a LEI")
        lei = normalize_identifier("lei", record_id)

        legal_name = entity.get("legalName")
        legal_names = _strings(legal_name)
        if not legal_names:
            raise ValueError(f"GLEIF record {lei} is missing a legal name")

        headquarters = entity.get("headquartersAddress")
        legal_address = entity.get("legalAddress")
        headquarters_country = headquarters.get("country") if isinstance(headquarters, Mapping) else None
        legal_country = legal_address.get("country") if isinstance(legal_address, Mapping) else None
        country_code = _alpha2(headquarters_country) or _alpha2(legal_country) or _alpha2(entity.get("jurisdiction"))
        if country_code is None:
            raise ValueError(f"GLEIF record {lei} is missing a valid country code")

        jurisdiction = _alpha2(entity.get("jurisdiction"))
        aliases = []
        for name in _strings(entity.get("otherNames")) + _strings(entity.get("transliteratedOtherNames")):
            if name not in aliases and name != legal_names[0]:
                aliases.append(name)

        candidate_owner = f"candidate:{self.definition.id}:{lei}"
        identifiers = [
            Identifier(
                owner_id=candidate_owner,
                type="lei",
                value=lei,
                country_code=country_code,
                source_id=self.definition.id,
            )
        ]
        for bic in dict.fromkeys(_strings(attributes.get("bic"))):
            identifiers.append(
                Identifier(
                    owner_id=candidate_owner,
                    type="bic",
                    value=normalize_identifier("bic", bic),
                    country_code=country_code,
                    source_id=self.definition.id,
                )
            )
        registered_as = _strings(entity.get("registeredAs"))
        if registered_as:
            identifiers.append(
                Identifier(
                    owner_id=candidate_owner,
                    type="national_registration",
                    value=registered_as[0],
                    country_code=country_code,
                    source_id=self.definition.id,
                )
            )

        links = record.get("links")
        source_uri = links.get("self") if isinstance(links, Mapping) else None
        if not isinstance(source_uri, str) or not source_uri:
            source_uri = f"{self.endpoint}/{lei}"

        return CandidateRecord(
            source_id=self.definition.id,
            source_record_id=lei,
            legal_name=legal_names[0],
            country_code=country_code,
            regulator_jurisdiction=jurisdiction,
            aliases=aliases,
            operating_markets=[country_code],
            identifiers=identifiers,
            source_uri=source_uri,
        )
