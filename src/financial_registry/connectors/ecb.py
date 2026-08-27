from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timezone
from io import BytesIO
from typing import Any
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import httpx
import pycountry

from ..domain import CandidateRecord, Identifier, SourceDefinition, SourceType, TrustTier
from ..normalize import normalize_identifier
from ..snapshots import FilesystemSnapshotStore, RawSnapshot

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_SHEET_RE = re.compile(r"xl/worksheets/sheet(\d+)\.xml$")
_HREF_RE = re.compile(r"href=[\"']([^\"']+\.xlsx(?:\?[^\"']*)?)[\"']", re.IGNORECASE)
_COUNTRY_ALIASES = {
    "CZECH REPUBLIC": "CZ",
    "TÜRKIYE": "TR",
    "TURKEY": "TR",
}
_ECB_TYPE_TO_CATEGORY = {
    "CI": "commercial_bank",
    "CI-B": "foreign_branch",
    "BR": "foreign_branch",
    "FH": "financial_holding_company",
    "MFH": "financial_holding_company",
}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _country_code(value: Any) -> str | None:
    value = _text(value)
    if not value:
        return None
    upper = value.upper()
    if len(upper) == 2 and upper.isascii() and upper.isalpha():
        return upper
    if upper in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[upper]
    try:
        return pycountry.countries.lookup(value).alpha_2
    except LookupError:
        return None


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "s":
        value = cell.find(_NS + "v")
        if value is None or value.text is None:
            return ""
        index = int(value.text)
        return shared_strings[index] if 0 <= index < len(shared_strings) else ""
    if cell_type == "inlineStr":
        return "".join(text.text or "" for text in cell.iter(_NS + "t"))
    value = cell.find(_NS + "v")
    return value.text or "" if value is not None else ""


def _column(reference: str | None) -> str | None:
    if not reference:
        return None
    match = re.match(r"([A-Z]+)", reference.upper())
    return match.group(1) if match else None


def _read_xlsx_sheets(body: bytes) -> list[list[dict[str, str]]]:
    with ZipFile(BytesIO(body)) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared_strings = ["".join(text.text or "" for text in item.iter(_NS + "t")) for item in root.findall(_NS + "si")]

        sheet_paths = []
        for name in archive.namelist():
            match = _SHEET_RE.match(name)
            if match:
                sheet_paths.append((int(match.group(1)), name))
        sheets: list[list[dict[str, str]]] = []
        for _, path in sorted(sheet_paths)[:2]:
            root = ET.fromstring(archive.read(path))
            rows: list[dict[str, str]] = []
            for row in root.findall(".//" + _NS + "row"):
                values: dict[str, str] = {}
                for cell in row.findall(_NS + "c"):
                    column = _column(cell.attrib.get("r"))
                    if column:
                        values[column] = _cell_value(cell, shared_strings)
                rows.append(values)
            sheets.append(rows)
        return sheets


class ECBConnector:
    """Fetch and normalize the ECB supervised-entity XLSX publication."""

    index_url = "https://www.bankingsupervision.europa.eu/framework/supervised-banks/html/index.en.html"

    def __init__(
        self,
        snapshot_store: FilesystemSnapshotStore,
        *,
        client: Any | None = None,
        workbook_url: str | None = None,
        max_records: int | None = 1_000,
        clock: Callable[[], datetime] | None = None,
    ):
        if max_records is not None and max_records < 1:
            raise ValueError("max_records must be positive or None")
        self.snapshot_store = snapshot_store
        self.client = client or httpx.Client(timeout=30.0, follow_redirects=True)
        self.workbook_url = workbook_url
        self.max_records = max_records
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.definition = SourceDefinition(
            id="src_ecb_supervised",
            publisher="European Central Bank",
            jurisdiction="EU",
            source_type=SourceType.REGULATOR,
            url=self.index_url,
            terms_url=self.index_url,
            trust_tier=TrustTier.AUTHORITATIVE,
            check_frequency="weekly",
            connector_version="ecb-supervised-xlsx-v1",
        )

    @staticmethod
    def _discover_workbook_url(html: str) -> str:
        for href in _HREF_RE.findall(html):
            if "ssm.listofsupervisedentities" not in href.lower() or "annex_changes" in href.lower():
                continue
            workbook_url = urljoin(ECBConnector.index_url, href)
            parsed = urlparse(workbook_url)
            if parsed.scheme != "https" or parsed.hostname != "www.bankingsupervision.europa.eu":
                raise ValueError("ECB workbook URL must remain on the official HTTPS host")
            return workbook_url
        raise ValueError("ECB supervised-entities workbook link was not found")

    def fetch(self) -> RawSnapshot:
        workbook_url = self.workbook_url
        if workbook_url is None:
            index_response = self.client.get(self.index_url)
            index_response.raise_for_status()
            workbook_url = self._discover_workbook_url(index_response.content.decode("utf-8", errors="replace"))
        self.workbook_url = workbook_url
        workbook_response = self.client.get(workbook_url)
        workbook_response.raise_for_status()
        body = workbook_response.content
        if not body:
            raise ValueError("ECB workbook response is empty")
        return self.snapshot_store.put(self.definition.id, self.clock(), body)

    def normalize(self, snapshot: RawSnapshot) -> list[CandidateRecord]:
        if snapshot.source_id != self.definition.id:
            raise ValueError(f"ECB snapshot source mismatch: {snapshot.source_id}")
        sheets = _read_xlsx_sheets(self.snapshot_store.read(snapshot))
        candidates: list[CandidateRecord] = []
        if sheets:
            candidates.extend(self._normalize_sheet(sheets[0], lei_column="C", type_column="H", name_column="L", country_column="R"))
        if len(sheets) > 1 and (self.max_records is None or len(candidates) < self.max_records):
            candidates.extend(self._normalize_sheet(sheets[1], lei_column="B", type_column="F", name_column="J", country_column=None))
        return candidates[: self.max_records] if self.max_records is not None else candidates

    def _normalize_sheet(
        self,
        rows: list[dict[str, str]],
        *,
        lei_column: str,
        type_column: str,
        name_column: str,
        country_column: str | None,
    ) -> list[CandidateRecord]:
        current_country: str | None = None
        candidates: list[CandidateRecord] = []
        for row in rows:
            source_id = _text(row.get(lei_column))
            name = _text(row.get(name_column))
            if not source_id:
                group_country = _country_code(name)
                if group_country:
                    current_country = group_country
                continue
            if "MFI" in source_id.upper() and "LEI" in source_id.upper():
                continue
            if not name:
                continue
            country = _country_code(row.get(country_column)) if country_column else None
            country = country or current_country
            if country is None:
                raise ValueError(f"ECB record {source_id} is missing a country")
            names = [part.strip() for part in re.split(r"\s*;\s*", name) if part.strip()]
            if not names:
                continue
            normalized_id = normalize_identifier("lei" if len(source_id.replace(" ", "")) == 20 else "ecb_mfi", source_id)
            identifier_type = "lei" if len(normalized_id) == 20 else "ecb_mfi"
            candidate_owner = f"candidate:{self.definition.id}:{normalized_id}"
            identifier = Identifier(
                owner_id=candidate_owner,
                type=identifier_type,
                value=normalized_id,
                country_code=country,
                source_id=self.definition.id,
            )
            type_code = (_text(row.get(type_column)) or "").upper()
            category = _ECB_TYPE_TO_CATEGORY.get(type_code, f"ecb_type:{type_code.lower()}" if type_code else "ecb_supervised_entity")
            candidates.append(
                CandidateRecord(
                    source_id=self.definition.id,
                    source_record_id=normalized_id,
                    legal_name=names[0],
                    country_code=country,
                    regulator_jurisdiction=country,
                    regulator_identifier=normalized_id,
                    categories=[category],
                    aliases=names[1:],
                    operating_markets=[country],
                    identifiers=[identifier],
                    source_uri=self.workbook_url or self.index_url,
                )
            )
            if self.max_records is not None and len(candidates) >= self.max_records:
                break
        return candidates
