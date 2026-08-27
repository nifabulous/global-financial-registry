"""Validation and loading for reviewed institution-to-Wikidata mappings."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .domain import RegistryInput

_QID_PATTERN = re.compile(r"Q[1-9][0-9]*\Z")


class WikidataMappingRecord(BaseModel):
    """One explicitly approved institution-to-Wikidata link."""

    model_config = ConfigDict(extra="forbid")

    institution_id: str = Field(min_length=1)
    qid: str
    review_status: Literal["approved"]
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    note: str | None = None

    @field_validator("institution_id", "qid", mode="before")
    @classmethod
    def strip_required_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("reviewed_by", "note", mode="before")
    @classmethod
    def strip_optional_text(cls, value):
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        return cleaned or None

    @field_validator("institution_id")
    @classmethod
    def validate_institution_id(cls, value: str) -> str:
        if not value:
            raise ValueError("institution_id must not be empty")
        return value

    @field_validator("qid")
    @classmethod
    def validate_qid(cls, value: str) -> str:
        if not _QID_PATTERN.fullmatch(value):
            raise ValueError("qid must be a Wikidata Q-ID such as Q123")
        return value

    @field_validator("reviewed_by")
    @classmethod
    def validate_reviewer(cls, value: str | None) -> str | None:
        if value is not None and not value:
            raise ValueError("reviewed_by must not be empty when provided")
        return value

    @field_validator("reviewed_at")
    @classmethod
    def validate_reviewed_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("reviewed_at must be timezone-aware UTC")
        return value


class WikidataMappingFile(BaseModel):
    """The JSON envelope used for the reviewed mapping allowlist."""

    model_config = ConfigDict(extra="forbid")

    mappings: list[WikidataMappingRecord]


def load_reviewed_wikidata_mappings(
    path: str | Path,
    registry: RegistryInput,
) -> dict[str, str]:
    """Load and validate approved mappings against a curated registry.

    The returned dictionary is intentionally the narrow shape accepted by
    ``WikidataCommonsLogoConnector``. Unknown institutions, duplicate
    institution IDs, and duplicate Q-IDs fail closed instead of being guessed
    or silently overwritten.
    """

    mapping_path = Path(path)
    payload = json.loads(mapping_path.read_text(encoding="utf-8"))
    mapping_file = WikidataMappingFile.model_validate(payload)
    institution_ids = {institution.id for institution in registry.institutions}
    links: dict[str, str] = {}
    qid_owners: dict[str, str] = {}
    for record in sorted(mapping_file.mappings, key=lambda item: (item.institution_id, item.qid)):
        if record.institution_id not in institution_ids:
            raise ValueError(f"unknown institution in Wikidata mapping: {record.institution_id}")
        if record.institution_id in links:
            raise ValueError(f"duplicate institution in Wikidata mapping: {record.institution_id}")
        previous_owner = qid_owners.get(record.qid)
        if previous_owner is not None:
            raise ValueError(f"duplicate Q-ID in Wikidata mapping: {record.qid} ({previous_owner})")
        links[record.institution_id] = record.qid
        qid_owners[record.qid] = record.institution_id
    return links


__all__ = [
    "WikidataMappingFile",
    "WikidataMappingRecord",
    "load_reviewed_wikidata_mappings",
]
