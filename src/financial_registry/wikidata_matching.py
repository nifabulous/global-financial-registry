"""Human-reviewable Wikidata entity suggestions for registry institutions."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from .domain import Institution
from .normalize import normalize_name

_QID_PATTERN = re.compile(r"Q[1-9][0-9]*\Z")
_DEFAULT_USER_AGENT = (
    "global-financial-registry/0.1 (+https://github.com/nifabulous/global-financial-registry)"
)


@dataclass(frozen=True)
class WikidataSuggestion:
    """One ranked Wikidata search result awaiting human review."""

    institution_id: str
    query: str
    qid: str
    label: str
    description: str | None
    rank: int
    exact_label_match: bool
    source_uri: str


@dataclass(frozen=True)
class WikidataMatchResult:
    """Suggestions and non-fatal warnings from one matching run."""

    suggestions: tuple[WikidataSuggestion, ...]
    warnings: tuple[str, ...] = ()


class WikidataEntityMatcher:
    """Suggest Wikidata entities by name without creating institution mappings.

    Wikidata name search is inherently ambiguous, especially for similarly named
    banks in different jurisdictions. This class only emits ranked evidence for
    a review queue; callers must explicitly approve a Q-ID before passing it to
    :class:`WikidataCommonsLogoConnector`.
    """

    endpoint = "https://www.wikidata.org/w/api.php"
    max_results_limit = 50

    def __init__(
        self,
        *,
        client: Any | None = None,
        max_results: int = 5,
        user_agent: str = _DEFAULT_USER_AGENT,
    ) -> None:
        if (
            not isinstance(max_results, int)
            or isinstance(max_results, bool)
            or not 1 <= max_results <= self.max_results_limit
        ):
            raise ValueError(f"max_results must be between 1 and {self.max_results_limit}")
        self.client = client or httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": user_agent},
        )
        self.max_results = max_results

    def suggest(self, institutions: Iterable[Institution]) -> WikidataMatchResult:
        """Return deterministic, ranked suggestions for the supplied institutions."""

        ordered = sorted(institutions, key=lambda item: (item.id, item.canonical_key))
        suggestions: list[WikidataSuggestion] = []
        warnings: list[str] = []
        for institution in ordered:
            query = institution.legal_name.strip()
            if not query:
                warnings.append(f"{institution.id} has no legal name for Wikidata search")
                continue

            results = self._search(query)
            if not results:
                warnings.append(f"{institution.id} has no Wikidata search results for '{query}'")
                continue
            rank = 0
            for result in results:
                qid = result.get("id")
                if not isinstance(qid, str) or not _QID_PATTERN.fullmatch(qid):
                    continue
                rank += 1
                label = result.get("label")
                if not isinstance(label, str) or not label.strip():
                    label = qid
                else:
                    label = label.strip()
                description = result.get("description")
                if not isinstance(description, str) or not description.strip():
                    description = None
                else:
                    description = description.strip()
                suggestions.append(
                    WikidataSuggestion(
                        institution_id=institution.id,
                        query=query,
                        qid=qid,
                        label=label,
                        description=description,
                        rank=rank,
                        exact_label_match=normalize_name(label) == normalize_name(query),
                        source_uri=f"https://www.wikidata.org/wiki/{qid}",
                    )
                )

        return WikidataMatchResult(tuple(suggestions), tuple(warnings))

    def _search(self, query: str) -> list[Mapping[str, Any]]:
        response = self.client.get(
            self.endpoint,
            params={
                "action": "wbsearchentities",
                "format": "json",
                "formatversion": "2",
                "language": "en",
                "uselang": "en",
                "search": query,
                "limit": str(self.max_results),
            },
        )
        response.raise_for_status()
        payload = response.json()
        raw_results = payload.get("search") if isinstance(payload, Mapping) else None
        if not isinstance(raw_results, list):
            raise ValueError("Wikidata search response search must be a list")
        return [item for item in raw_results if isinstance(item, Mapping)]


__all__ = ["WikidataEntityMatcher", "WikidataMatchResult", "WikidataSuggestion"]
