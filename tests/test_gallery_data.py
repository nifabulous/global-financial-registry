import json
from pathlib import Path

import pytest

from financial_registry.gallery_data import (
    GalleryDataError,
    build_gallery_data,
    verify_gallery_data,
)


def test_gallery_projection_keeps_only_asset_owners_and_sources(tmp_path: Path) -> None:
    source = {"id": "src-used", "publisher": "Used source"}
    payload = {
        "asset_root": "assets",
        "institutions": [
            {"id": "inst-used", "short_name": "Used Bank"},
            {"id": "inst-unused", "short_name": "Unused Bank"},
        ],
        "brands": [{"id": "brand-unused", "display_name": "Unused Brand"}],
        "identifiers": [{"owner_id": "inst-unused", "value": "not needed"}],
        "aliases": [],
        "rekey_events": [],
        "relationships": [],
        "assets": [{"id": "asset-used", "owner_id": "inst-used", "source_id": "src-used"}],
        "sources": [source, {"id": "src-unused", "publisher": "Unused source"}],
        "source_runs": [{"id": "run-1", "source_id": "src-used"}],
    }
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(payload), encoding="utf-8")

    projection = build_gallery_data(registry_path)

    assert projection["coverage"] == {"total_entities": 3}
    assert [item["id"] for item in projection["institutions"]] == ["inst-used"]
    assert projection["brands"] == []
    assert projection["assets"] == payload["assets"]
    assert projection["sources"] == [source]


def test_gallery_projection_rejects_unknown_owner_or_source(tmp_path: Path) -> None:
    base = {
        "asset_root": "assets",
        "institutions": [{"id": "inst-used"}],
        "brands": [],
        "identifiers": [],
        "aliases": [],
        "rekey_events": [],
        "relationships": [],
        "assets": [{"id": "asset-used", "owner_id": "inst-used", "source_id": "src-used"}],
        "sources": [{"id": "src-used"}],
        "source_runs": [],
    }
    registry_path = tmp_path / "registry.json"

    unknown_owner = {**base, "assets": [{**base["assets"][0], "owner_id": "inst-missing"}]}
    registry_path.write_text(json.dumps(unknown_owner), encoding="utf-8")
    with pytest.raises(GalleryDataError, match="unknown owners"):
        build_gallery_data(registry_path)

    unknown_source = {**base, "assets": [{**base["assets"][0], "source_id": "src-missing"}]}
    registry_path.write_text(json.dumps(unknown_source), encoding="utf-8")
    with pytest.raises(GalleryDataError, match="unknown sources"):
        build_gallery_data(registry_path)


def test_gallery_projection_verification_rejects_stale_data(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.json"
    gallery_path = tmp_path / "gallery.json"
    registry_path.write_text(json.dumps({"institutions": [], "brands": [], "assets": [], "sources": []}), encoding="utf-8")
    gallery_path.write_text("{}", encoding="utf-8")

    with pytest.raises(GalleryDataError, match="does not match"):
        verify_gallery_data(registry_path, gallery_path)
