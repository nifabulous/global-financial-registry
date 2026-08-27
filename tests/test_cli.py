from typer.testing import CliRunner

from financial_registry.cli import _registry_payload, app
from financial_registry.domain import RegistryInput, SourceRun, SourceRunStatus
from financial_registry.logo_sources import LogoSourceResult
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


def test_wikidata_logo_discover_requires_reviewed_mapping(tmp_path, monkeypatch):
    mapping = tmp_path / "wikidata-mappings.json"
    mapping.write_text(
        '{"mappings":[{"institution_id":"inst_example_bank","qid":"Q100",'
        '"review_status":"approved"}]}\n',
        encoding="utf-8",
    )
    output = tmp_path / "wikidata-logo-candidates.json"

    class FakeConnector:
        def discover(self, institution_qids):
            assert institution_qids == {"inst_example_bank": "Q100"}
            return LogoSourceResult(candidates=(), warnings=("review logo",))

    monkeypatch.setattr("financial_registry.cli.WikidataCommonsLogoConnector", FakeConnector)
    result = CliRunner().invoke(
        app,
        [
            "wikidata-logo-discover",
            "data/fixtures/candidates.json",
            str(mapping),
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert "0 candidates" in result.stdout
    assert output.read_text(encoding="utf-8") == '{"candidates":[],"warnings":["review logo"]}\n'


def test_wikidata_logo_discover_fails_closed_for_unapproved_mapping(tmp_path):
    mapping = tmp_path / "wikidata-mappings.json"
    mapping.write_text(
        '{"mappings":[{"institution_id":"inst_example_bank","qid":"Q100",'
        '"review_status":"candidate"}]}\n',
        encoding="utf-8",
    )
    output = tmp_path / "wikidata-logo-candidates.json"

    result = CliRunner().invoke(
        app,
        [
            "wikidata-logo-discover",
            "data/fixtures/candidates.json",
            str(mapping),
            str(output),
        ],
    )

    assert result.exit_code == 1
    assert "review_status" in result.stderr
    assert not output.exists()


def test_source_pilot_writes_merged_registry_with_bounded_limits(tmp_path, monkeypatch):
    output = tmp_path / "registry.json"

    class PilotResult:
        registry = RegistryInput()
        report = type("Report", (), {"candidate_count": 0})()
        warnings = ("source warning",)

    def fake_run(connectors, *, now):
        assert [connector.definition.id for connector in connectors] == [
            "src_gleif_lei",
            "src_fdic_bankfind",
            "src_ecb_supervised",
        ]
        assert [connector.max_records for connector in connectors] == [7, 7, 7]
        assert now.isoformat() == "2026-08-27T12:00:00+00:00"
        return PilotResult()

    monkeypatch.setattr("financial_registry.cli.run_registry_pilot", fake_run)
    result = CliRunner().invoke(
        app,
        [
            "source-pilot",
            str(output),
            "--snapshot-dir",
            str(tmp_path / "snapshots"),
            "--max-records",
            "7",
            "--generated-at",
            "2026-08-27T12:00:00+00:00",
        ],
    )

    assert result.exit_code == 0
    assert "0 institutions" in result.stdout
    assert "1 warnings" in result.stdout
    assert '"institutions":[]' in output.read_text(encoding="utf-8")


def test_registry_payload_relativizes_colocated_snapshots(tmp_path):
    registry = RegistryInput(
        source_runs=[
            SourceRun(
                id="src_demo:run",
                source_id="src_demo",
                started_at="2026-08-27T12:00:00+00:00",
                finished_at="2026-08-27T12:00:00+00:00",
                status=SourceRunStatus.SUCCEEDED,
                snapshot_path=str(tmp_path / "snapshots" / "demo.bin"),
                snapshot_sha256="a" * 64,
            )
        ]
    )

    payload = _registry_payload(registry, tmp_path / "registry.json")

    assert payload["source_runs"][0]["snapshot_path"] == "snapshots/demo.bin"
