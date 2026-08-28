import hashlib
import json
from pathlib import Path

import pytest

from financial_registry.logo_manifest import (
    LogoManifestError,
    build_logo_manifest,
    serialize_logo_manifest,
    verify_logo_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "data" / "registry-with-logos.json"
MANIFEST_PATH = ROOT / "data" / "logo-manifest.json"


def _write_fixture_registry(tmp_path: Path, body: bytes = b"<svg />") -> Path:
    asset_root = tmp_path / "assets"
    asset_dir = asset_root / "logos"
    asset_dir.mkdir(parents=True)
    asset_path = asset_dir / "fixture.svg"
    asset_path.write_bytes(body)
    payload = {
        "asset_root": "assets",
        "institutions": [
            {
                "id": "inst-fixture",
                "canonical_key": "institution:fixture:1",
                "legal_name": "Fixture Bank",
                "normalized_name": "fixture bank",
                "country_code": "US",
                "regulator_jurisdiction": "US",
            }
        ],
        "brands": [],
        "identifiers": [],
        "aliases": [],
        "rekey_events": [],
        "relationships": [],
        "assets": [
            {
                "id": "asset-fixture",
                "owner_id": "inst-fixture",
                "variant": "primary",
                "format": "svg",
                "source_id": "src-fixture",
                "source_uri": "https://example.test/fixture.svg",
                "rights_status": "redistributable",
                "review_status": "approved",
                "sha256": hashlib.sha256(body).hexdigest(),
                "binary_path": "assets/logos/fixture.svg",
                "staging_path": "logos/fixture.svg",
            }
        ],
        "sources": [
            {
                "id": "src-fixture",
                "publisher": "Fixture publisher",
                "jurisdiction": "US",
                "source_type": "repository",
                "url": "https://example.test",
                "trust_tier": "submitted",
                "check_frequency": "on-demand",
                "connector_version": "fixture-1",
            }
        ],
        "source_runs": [],
    }
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(payload), encoding="utf-8")
    return registry_path


def test_manifest_captures_asset_owner_source_rights_and_file_checksum(tmp_path: Path) -> None:
    registry_path = _write_fixture_registry(tmp_path)

    manifest = build_logo_manifest(registry_path)

    assert manifest["asset_count"] == 1
    assert manifest["registry_sha256"]
    assert manifest["assets"] == [
        {
            "asset_id": "asset-fixture",
            "owner_id": "inst-fixture",
            "owner_kind": "institution",
            "source_id": "src-fixture",
            "rights_status": "redistributable",
            "review_status": "approved",
            "binary_path": "assets/logos/fixture.svg",
            "staging_path": "logos/fixture.svg",
            "sha256": hashlib.sha256(b"<svg />").hexdigest(),
            "bytes": len(b"<svg />"),
        }
    ]


def test_manifest_verification_rejects_changed_binary(tmp_path: Path) -> None:
    registry_path = _write_fixture_registry(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(build_logo_manifest(registry_path)), encoding="utf-8")
    (tmp_path / "assets" / "logos" / "fixture.svg").write_bytes(b"changed")

    with pytest.raises(LogoManifestError, match="checksum"):
        verify_logo_manifest(registry_path, manifest_path)


def test_manifest_serialization_keeps_one_machine_checkable_entry_per_line(tmp_path: Path) -> None:
    manifest = build_logo_manifest(_write_fixture_registry(tmp_path))

    serialized = serialize_logo_manifest(manifest)

    assert json.loads(serialized) == manifest
    assert len(serialized.splitlines()) <= 20


def test_committed_manifest_matches_every_registry_asset() -> None:
    manifest = verify_logo_manifest(REGISTRY_PATH, MANIFEST_PATH)

    assert manifest["asset_count"] == len(json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))["assets"])
