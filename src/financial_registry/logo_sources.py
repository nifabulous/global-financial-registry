"""Metadata-only logo sources backed by Wikidata and Wikimedia Commons."""

from __future__ import annotations

import html as html_module
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from .domain import (
    AssetCandidate,
    AssetVariant,
    ReviewStatus,
    RightsStatus,
    SourceDefinition,
    SourceType,
    TrustTier,
)
from .ids import StableIdAllocator


@dataclass(frozen=True)
class LogoSourceResult:
    """Candidates and non-fatal source warnings from one metadata run."""

    candidates: tuple[AssetCandidate, ...]
    warnings: tuple[str, ...] = ()


class WikidataCommonsLogoConnector:
    """Resolve explicit Wikidata IDs to Commons logo metadata without image downloads.

    The connector intentionally requires a curated ``institution_id -> Wikidata
    Q-ID`` mapping. Name search is ambiguous for banks, and an accidental match
    could attach the wrong brand to an institution. The P154 claim and Commons
    metadata provide discovery and licensing evidence; candidates still start as
    ``source_link_only`` and require human review before publication.
    """

    wikidata_endpoint = "https://www.wikidata.org/w/api.php"
    commons_endpoint = "https://commons.wikimedia.org/w/api.php"
    max_ids_per_request = 50

    def __init__(
        self,
        *,
        client: Any | None = None,
        id_allocator: StableIdAllocator | None = None,
        user_agent: str = "global-financial-registry/0.1 (+https://github.com/nifabulous/global-financial-registry)",
    ):
        self.client = client or httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": user_agent},
        )
        self.id_allocator = id_allocator or StableIdAllocator()
        self.definition = SourceDefinition(
            id="src_wikidata_commons_logo",
            publisher="Wikidata and Wikimedia Commons",
            jurisdiction="GLOBAL",
            source_type=SourceType.REPOSITORY,
            url=self.wikidata_endpoint,
            terms_url="https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use",
            trust_tier=TrustTier.APPROVED,
            check_frequency="weekly",
            connector_version="wikidata-commons-logo-v1",
        )

    def discover(self, institution_qids: Mapping[str, str]) -> LogoSourceResult:
        """Return link-only logo candidates and warnings for explicit Q-ID links."""

        links = sorted(institution_qids.items(), key=lambda item: (item[0], item[1]))
        for institution_id, qid in links:
            if not re.fullmatch(r"Q[1-9][0-9]*", qid):
                raise ValueError(f"invalid Wikidata Q-ID for {institution_id}: {qid}")

        entity_claims = self._fetch_entities(sorted({qid for _, qid in links}))
        claims_by_institution: list[tuple[str, str, str, float]] = []
        warnings: list[str] = []
        for institution_id, qid in links:
            claims = entity_claims.get(qid)
            if not isinstance(claims, Mapping):
                warnings.append(f"{institution_id}:{qid} was not returned by Wikidata")
                continue
            logo_claims = claims.get("P154")
            files = self._extract_files(logo_claims)
            if not files:
                warnings.append(f"{institution_id}:{qid} has no Wikidata P154 logo claim")
                continue
            seen_files: set[str] = set()
            for filename, confidence in files:
                file_key = self._file_key(filename)
                if file_key in seen_files:
                    continue
                seen_files.add(file_key)
                claims_by_institution.append((institution_id, qid, filename, confidence))

        metadata = self._fetch_commons_metadata(sorted({filename for _, _, filename, _ in claims_by_institution}))
        candidates: list[AssetCandidate] = []
        for institution_id, qid, filename, confidence in claims_by_institution:
            info = metadata.get(self._file_key(filename))
            if info is None:
                warnings.append(f"{institution_id}:{qid}:{filename} has no Commons image metadata")
                continue
            image_url = info.get("url")
            if not self._is_allowed_media_url(image_url):
                warnings.append(f"{institution_id}:{qid}:{filename} has no allowed HTTPS image URL")
                continue
            file_title = self._file_title(filename)
            commons_url = f"https://commons.wikimedia.org/wiki/{quote(file_title, safe=':')}"
            license_name = self._metadata_text(info.get("extmetadata"), "LicenseShortName") or self._metadata_text(
                info.get("extmetadata"), "UsageTerms"
            )
            license_url = self._metadata_text(info.get("extmetadata"), "LicenseUrl")
            attribution = self._metadata_text(info.get("extmetadata"), "Attribution") or self._metadata_text(
                info.get("extmetadata"), "Artist"
            )
            candidates.append(
                AssetCandidate(
                    id=self.id_allocator.allocate("asset", f"wikimedia:{institution_id}:{self._file_key(filename)}:{image_url}"),
                    owner_id=institution_id,
                    variant=AssetVariant.PRIMARY,
                    source_id=self.definition.id,
                    source_uri=image_url,
                    rights_status=RightsStatus.SOURCE_LINK_ONLY,
                    review_status=ReviewStatus.CANDIDATE,
                    discovery_method="wikidata_p154_commons",
                    confidence=confidence,
                    license_name=license_name,
                    license_url=license_url,
                    attribution_text=attribution,
                    rights_note=(
                        "Wikidata P154 points to a Wikimedia Commons file; Commons license metadata is "
                        f"evidence only and still requires review. File page: {commons_url}"
                    ),
                )
            )

        candidates.sort(key=lambda candidate: (candidate.owner_id, candidate.source_uri, -candidate.confidence))
        warnings.sort()
        return LogoSourceResult(tuple(candidates), tuple(warnings))

    def _fetch_entities(self, qids: list[str]) -> dict[str, Mapping[str, Any]]:
        entities: dict[str, Mapping[str, Any]] = {}
        for start in range(0, len(qids), self.max_ids_per_request):
            batch = qids[start : start + self.max_ids_per_request]
            response = self.client.get(
                self.wikidata_endpoint,
                params={
                    "action": "wbgetentities",
                    "format": "json",
                    "formatversion": "2",
                    "ids": "|".join(batch),
                    "props": "claims",
                },
            )
            response.raise_for_status()
            payload = response.json()
            returned = payload.get("entities") if isinstance(payload, Mapping) else None
            if not isinstance(returned, Mapping):
                raise ValueError("Wikidata response entities must be an object")
            for qid, entity in returned.items():
                if isinstance(entity, Mapping):
                    claims = entity.get("claims")
                    entities[str(qid)] = claims if isinstance(claims, Mapping) else {}
        return entities

    def _fetch_commons_metadata(self, filenames: list[str]) -> dict[str, Mapping[str, Any]]:
        metadata: dict[str, Mapping[str, Any]] = {}
        for start in range(0, len(filenames), self.max_ids_per_request):
            batch = filenames[start : start + self.max_ids_per_request]
            response = self.client.get(
                self.commons_endpoint,
                params={
                    "action": "query",
                    "format": "json",
                    "formatversion": "2",
                    "prop": "imageinfo",
                    "iiprop": "url|mime|extmetadata",
                    "titles": "|".join(self._file_title(filename) for filename in batch),
                },
            )
            response.raise_for_status()
            payload = response.json()
            query = payload.get("query") if isinstance(payload, Mapping) else None
            pages = query.get("pages") if isinstance(query, Mapping) else None
            if isinstance(pages, Mapping):
                pages = list(pages.values())
            if not isinstance(pages, list):
                raise ValueError("Commons response pages must be a list or object")
            for page in pages:
                if not isinstance(page, Mapping):
                    continue
                imageinfo = page.get("imageinfo")
                if not isinstance(imageinfo, list) or not imageinfo or not isinstance(imageinfo[0], Mapping):
                    continue
                title = page.get("title")
                if isinstance(title, str):
                    metadata[self._file_key(title)] = dict(imageinfo[0])
        return metadata

    @staticmethod
    def _extract_files(claims: Any) -> list[tuple[str, float]]:
        if not isinstance(claims, list):
            return []
        ranked: list[tuple[int, str]] = []
        for claim in claims:
            if not isinstance(claim, Mapping) or claim.get("rank") == "deprecated":
                continue
            mainsnak = claim.get("mainsnak")
            datavalue = mainsnak.get("datavalue") if isinstance(mainsnak, Mapping) else None
            filename = datavalue.get("value") if isinstance(datavalue, Mapping) else None
            if not isinstance(filename, str) or not filename.strip():
                continue
            rank = 0 if claim.get("rank") == "preferred" else 1
            ranked.append((rank, filename.strip()))
        ranked.sort(key=lambda item: (item[0], item[1].casefold()))
        seen: set[str] = set()
        files: list[tuple[str, float]] = []
        for rank, filename in ranked:
            key = WikidataCommonsLogoConnector._file_key(filename)
            if key in seen:
                continue
            seen.add(key)
            files.append((filename, 0.85 if rank == 0 else 0.75))
        return files

    @staticmethod
    def _file_title(filename: str) -> str:
        value = filename.strip()
        return value if value.casefold().startswith("file:") else f"File:{value}"

    @staticmethod
    def _file_key(filename: str) -> str:
        value = WikidataCommonsLogoConnector._file_title(filename)[5:]
        return value.replace(" ", "_").casefold()

    @staticmethod
    def _is_allowed_media_url(value: Any) -> bool:
        if not isinstance(value, str):
            return False
        parsed = urlsplit(value)
        return parsed.scheme.casefold() == "https" and parsed.hostname.casefold() == "upload.wikimedia.org"

    @staticmethod
    def _metadata_text(metadata: Any, key: str) -> str | None:
        if not isinstance(metadata, Mapping):
            return None
        value = metadata.get(key)
        raw = value.get("value") if isinstance(value, Mapping) else value
        if not isinstance(raw, str):
            return None
        cleaned = html_module.unescape(re.sub(r"<[^>]+>", " ", raw))
        cleaned = " ".join(cleaned.split())
        return cleaned or None


__all__ = ["LogoSourceResult", "WikidataCommonsLogoConnector"]
