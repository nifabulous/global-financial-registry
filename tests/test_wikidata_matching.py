from __future__ import annotations

from collections.abc import Mapping

from financial_registry.domain import Institution
from financial_registry.wikidata_matching import WikidataEntityMatcher


def _institution(institution_id: str, legal_name: str) -> Institution:
    return Institution(
        id=institution_id,
        canonical_key=f"institution:source:{institution_id}",
        legal_name=legal_name,
        normalized_name=legal_name.casefold(),
        country_code="US",
        regulator_jurisdiction="US",
    )


class FakeResponse:
    def __init__(self, payload: Mapping):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self):
        self.calls: list[dict[str, str]] = []

    def get(self, url: str, params: dict[str, str]):
        self.calls.append({"url": url, **params})
        if params["search"] == "Acme Bank plc":
            return FakeResponse(
                {
                    "search": [
                        {"id": "Q100", "label": "Acme Bank plc", "description": "bank"},
                        {"id": "Q101", "label": "Acme Holdings", "description": "company"},
                    ]
                }
            )
        return FakeResponse({"search": []})


def test_matcher_returns_ranked_suggestions_without_creating_mappings():
    client = FakeClient()
    matcher = WikidataEntityMatcher(client=client, max_results=2)

    result = matcher.suggest(
        [_institution("inst_missing", "No Match Bank"), _institution("inst_acme", "Acme Bank plc")]
    )

    assert [(item.institution_id, item.qid, item.rank) for item in result.suggestions] == [
        ("inst_acme", "Q100", 1),
        ("inst_acme", "Q101", 2),
    ]
    assert result.suggestions[0].exact_label_match is True
    assert result.suggestions[0].source_uri == "https://www.wikidata.org/wiki/Q100"
    assert result.warnings == ("inst_missing has no Wikidata search results for 'No Match Bank'",)
    assert len(client.calls) == 2


def test_matcher_is_deterministic_for_input_order():
    client = FakeClient()
    matcher = WikidataEntityMatcher(client=client, max_results=1)
    institutions = [_institution("inst_acme", "Acme Bank plc")]

    first = matcher.suggest(institutions)
    second = matcher.suggest(reversed(institutions))

    assert first == second


def test_matcher_rejects_invalid_result_limit():
    try:
        WikidataEntityMatcher(client=FakeClient(), max_results=0)
    except ValueError as exc:
        assert "max_results" in str(exc)
    else:
        raise AssertionError("invalid max_results must be rejected")


def test_matcher_ranks_only_valid_wikidata_items():
    class MixedResultClient(FakeClient):
        def get(self, url: str, params: dict[str, str]):
            self.calls.append({"url": url, **params})
            return FakeResponse(
                {
                    "search": [
                        {"id": "P31", "label": "instance of"},
                        {"id": "Q200", "label": "Acme Bank plc"},
                    ]
                }
            )

    result = WikidataEntityMatcher(client=MixedResultClient(), max_results=2).suggest(
        [_institution("inst_acme", "Acme Bank plc")]
    )

    assert [(item.qid, item.rank) for item in result.suggestions] == [("Q200", 1)]
