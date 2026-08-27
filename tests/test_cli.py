from typer.testing import CliRunner

from financial_registry.cli import app


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
