import json

from typer.testing import CliRunner

from financial_registry.cli import app

runner = CliRunner()


def test_logo_derive_generates_raster_formats_with_source_links(demo_registry, tmp_path):
    input_path = tmp_path / "registry.json"
    output_path = tmp_path / "registry-derived.json"
    input_path.write_text(
        json.dumps(demo_registry.model_dump(mode="json")),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "logo-derive",
            str(input_path),
            str(output_path),
            "--formats",
            "png,webp,jpg",
            "--width",
            "32",
        ],
    )

    assert result.exit_code == 0, result.stdout
    derived = json.loads(output_path.read_text(encoding="utf-8"))
    generated = [asset for asset in derived["assets"] if asset.get("derived_from") == "asset_demo"]
    assert {asset["format"] for asset in generated} == {"png", "webp", "jpg"}
    assert all(asset["review_status"] == "approved" for asset in generated)
    assert all(asset["rights_status"] == "redistributable" for asset in generated)
    assert all((tmp_path / "asset_root" / asset["staging_path"]).is_file() for asset in generated)
