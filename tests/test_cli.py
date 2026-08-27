from typer.testing import CliRunner

from financial_registry.cli import app
from financial_registry.wikidata_matching import WikidataMatchResult, WikidataSuggestion


def test_validate_fixture_succeeds():
    result = CliRunner().invoke(app, ["validate", "data/fixtures/candidates.json"])
    assert result.exit_code == 0
    assert "valid" in result.stdout.lower()


def test_release_build_writes_manifest(tmp_path):
    result = CliRunner().invoke(
        app,
        [
            "release-build",
            "data/fixtures/candidates.json",
            str(tmp_path),
            "--version",
            "0.1.0",
            "--generated-at",
            "2026-08-26T00:00:00+00:00",
            "--generation-commit",
            "fixture-commit",
        ],
    )
    assert result.exit_code == 0
    assert (tmp_path / "schema-version.json").exists()
    assert (tmp_path / "checksums.txt").exists()


def test_release_build_failure_leaves_no_partial_output(tmp_path):
    output = tmp_path / "release"
    result = CliRunner().invoke(
        app,
        [
            "release-build",
            "data/fixtures/invalid.json",
            str(output),
            "--version",
            "not-semver",
            "--generated-at",
            "2026-08-26T00:00:00+00:00",
            "--generation-commit",
            "fixture-commit",
        ],
    )
    assert result.exit_code == 1
    assert not output.exists()


def test_logo_discover_writes_review_queue(tmp_path):
    output = tmp_path / "logo-candidates.json"
    result = CliRunner().invoke(app, ["logo-discover", "data/fixtures/candidates.json", str(output)])

    assert result.exit_code == 0
    assert "6 candidates" in result.stdout
    payload = output.read_text(encoding="utf-8")
    assert '"rights_status":"source_link_only"' in payload
    assert '"review_status":"candidate"' in payload


def test_wikidata_suggest_writes_review_queue(tmp_path, monkeypatch):
    output = tmp_path / "wikidata-suggestions.json"

    class FakeMatcher:
        def __init__(self, *, max_results):
            assert max_results == 3

        def suggest(self, institutions):
            assert [institution.id for institution in institutions] == [
                "inst_example_bank",
                "inst_example_wallet",
            ]
            return WikidataMatchResult(
                suggestions=(
                    WikidataSuggestion(
                        institution_id="inst_example_bank",
                        query="Example Bank plc",
                        qid="Q100",
                        label="Example Bank plc",
                        description="bank",
                        rank=1,
                        exact_label_match=True,
                        source_uri="https://www.wikidata.org/wiki/Q100",
                    ),
                ),
                warnings=("inst_example_wallet has no Wikidata search results for 'Example Wallet'",),
            )

    monkeypatch.setattr("financial_registry.cli.WikidataEntityMatcher", FakeMatcher)
    result = CliRunner().invoke(
        app,
        [
            "wikidata-suggest",
            "data/fixtures/candidates.json",
            str(output),
            "--max-results",
            "3",
        ],
    )

    assert result.exit_code == 0
    assert "1 suggestions" in result.stdout
    assert output.read_text(encoding="utf-8") == (
        '{"suggestions":[{"description":"bank","exact_label_match":true,'
        '"institution_id":"inst_example_bank","label":"Example Bank plc",'
        '"qid":"Q100","query":"Example Bank plc","rank":1,'
        '"source_uri":"https://www.wikidata.org/wiki/Q100"}],'
        '"warnings":["inst_example_wallet has no Wikidata search results for \'Example Wallet\'"]}\n'
    )
