from __future__ import annotations

from collections.abc import Mapping

from financial_registry.domain import ReviewStatus, RightsStatus
from financial_registry.logo_sources import WikidataCommonsLogoConnector


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
        if params["action"] == "wbgetentities":
            return FakeResponse(
                {
                    "entities": {
                        "Q100": {
                            "claims": {
                                "P154": [
                                    {
                                        "rank": "preferred",
                                        "mainsnak": {"datavalue": {"value": "Acme Bank logo.svg"}},
                                    }
                                ]
                            }
                        }
                    }
                }
            )
        return FakeResponse(
            {
                "query": {
                    "pages": [
                        {
                            "pageid": 1,
                            "title": "File:Acme Bank logo.svg",
                            "imageinfo": [
                                {
                                    "url": "https://upload.wikimedia.org/acme-bank-logo.svg",
                                    "mime": "image/svg+xml",
                                    "extmetadata": {
                                        "LicenseShortName": {"value": "CC BY-SA 4.0"},
                                        "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0/"},
                                        "Attribution": {"value": "Acme author"},
                                    },
                                }
                            ],
                        }
                    ]
                }
            }
        )


def test_wikidata_commons_source_emits_link_only_candidate_with_license_metadata():
    client = FakeClient()
    result = WikidataCommonsLogoConnector(client=client).discover({"inst_acme": "Q100"})

    assert result.warnings == ()
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.owner_id == "inst_acme"
    assert candidate.source_uri == "https://upload.wikimedia.org/acme-bank-logo.svg"
    assert candidate.rights_status is RightsStatus.SOURCE_LINK_ONLY
    assert candidate.review_status is ReviewStatus.CANDIDATE
    assert candidate.discovery_method == "wikidata_p154_commons"
    assert candidate.license_name == "CC BY-SA 4.0"
    assert candidate.license_url == "https://creativecommons.org/licenses/by-sa/4.0/"
    assert candidate.attribution_text == "Acme author"
    assert len(client.calls) == 2
    assert all(call["action"] in {"wbgetentities", "query"} for call in client.calls)


def test_wikidata_commons_source_is_deterministic_and_reports_missing_logos():
    class MissingLogoClient(FakeClient):
        def get(self, url: str, params: dict[str, str]):
            self.calls.append({"url": url, **params})
            return FakeResponse({"entities": {"Q100": {"claims": {}}}})

    client = MissingLogoClient()
    connector = WikidataCommonsLogoConnector(client=client)
    first = connector.discover({"inst_missing": "Q100", "inst_acme": "Q100"})
    second = connector.discover({"inst_acme": "Q100", "inst_missing": "Q100"})

    assert first.candidates == second.candidates == ()
    assert first.warnings == (
        "inst_acme:Q100 has no Wikidata P154 logo claim",
        "inst_missing:Q100 has no Wikidata P154 logo claim",
    )


def test_wikidata_commons_source_does_not_download_images():
    client = FakeClient()
    result = WikidataCommonsLogoConnector(client=client).discover({"inst_acme": "Q100"})

    assert result.candidates[0].source_uri.startswith("https://upload.wikimedia.org/")
    assert all("upload.wikimedia.org" not in call["url"] for call in client.calls)


def test_connector_default_client_sets_identifying_user_agent(monkeypatch):
    captured = {}

    class DummyClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("financial_registry.logo_sources.httpx.Client", DummyClient)

    WikidataCommonsLogoConnector()

    assert captured["headers"]["User-Agent"].startswith("global-financial-registry/")
