import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from PIL import Image, PngImagePlugin
from pydantic import ValidationError

from financial_registry.assets import (
    AssetPolicyError,
    AssetProcessor,
    FetchedAsset,
    _raise_url_fetcher,
    compute_imagehash,
)
from financial_registry.connectors.fixture import FixtureConnector
from financial_registry.domain import AssetCandidate, Identifier, ReleaseStatus, RightsStatus
from financial_registry.fetch_policy import (
    SafeHttpxAssetFetcher,
    UnsafeSourceUrl,
    validate_source_url,
)
from financial_registry.release import (
    ReleaseBuilder,
    ReleaseLifecycle,
    ReleaseValidationError,
    _hash_json,
)
from financial_registry.resolver import EntityResolver, ResolverIndex
from financial_registry.snapshots import FilesystemSnapshotStore


def _png_bytes(with_metadata: bool = False) -> bytes:
    image = Image.new("RGB", (1, 1), (0, 0, 0))
    output = io.BytesIO()
    if with_metadata:
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("Comment", "should not be published")
        image.save(output, format="PNG", pnginfo=metadata)
    else:
        image.save(output, format="PNG")
    return output.getvalue()


def test_fetcher_pins_single_validated_dns_answer_before_connecting():
    calls = 0
    requests = []

    def resolver(_host):
        nonlocal calls
        calls += 1
        return ["8.8.8.8"] if calls == 1 else ["127.0.0.1"]

    def transport(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"png")

    client = httpx.Client(transport=httpx.MockTransport(transport))
    try:
        fetched = SafeHttpxAssetFetcher(client, resolver).fetch("https://public.test/logo.png")
    finally:
        client.close()
    assert calls == 1
    assert str(requests[0].url).startswith("https://8.8.8.8/logo.png")
    assert requests[0].headers["host"] == "public.test"
    assert fetched.final_url == "https://public.test/logo.png"


def test_snapshot_store_rejects_symlinked_source_directory(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "snapshots"
    root.mkdir()
    (root / "src_demo").symlink_to(outside, target_is_directory=True)

    store = FilesystemSnapshotStore(root)
    with pytest.raises(ValueError, match="symlink|root"):
        store.put("src_demo", datetime(2026, 8, 26, tzinfo=timezone.utc), b"payload")
    assert list(outside.iterdir()) == []


def test_release_rejects_successful_source_run_without_snapshot(tmp_path, demo_registry):
    run = demo_registry.source_runs[0].model_copy(update={"snapshot_path": None, "snapshot_sha256": None})
    registry = demo_registry.model_copy(update={"source_runs": [run]})

    with pytest.raises(ReleaseValidationError, match="snapshot"):
        ReleaseBuilder().build(
            registry,
            "0.1.0",
            datetime(2026, 8, 26, tzinfo=timezone.utc),
            tmp_path / "release",
            generation_commit="test",
        )


def test_release_rejects_source_run_for_unknown_source(tmp_path, demo_registry):
    run = demo_registry.source_runs[0].model_copy(update={"source_id": "src_unknown"})
    registry = demo_registry.model_copy(update={"source_runs": [run]})

    with pytest.raises(ReleaseValidationError, match="source"):
        ReleaseBuilder().build(
            registry,
            "0.1.0",
            datetime(2026, 8, 26, tzinfo=timezone.utc),
            tmp_path / "release",
            generation_commit="test",
        )


def test_svg_dimensions_are_rejected_before_rasterization(monkeypatch):
    import cairosvg

    called = False

    def fake_svg2png(**_kwargs):
        nonlocal called
        called = True
        return _png_bytes()

    monkeypatch.setattr(cairosvg, "svg2png", fake_svg2png)
    body = b'<svg xmlns="http://www.w3.org/2000/svg" width="999999" height="999999"><rect/></svg>'

    with pytest.raises(AssetPolicyError, match="dimension"):
        AssetProcessor(max_dimension=4096)._sanitize_svg(body)
    assert called is False


def test_raster_sanitizer_restores_global_pillow_limit():
    old_limit = Image.MAX_IMAGE_PIXELS
    AssetProcessor(max_dimension=1)._sanitize_raster(_png_bytes())
    assert Image.MAX_IMAGE_PIXELS == old_limit


def test_raster_sanitizer_returns_normalized_bytes():
    body = _png_bytes(with_metadata=True)
    sanitized = AssetProcessor()._sanitize_and_normalize(
        FetchedAsset(
            url="https://example.test/logo.png",
            final_url="https://example.test/logo.png",
            body=body,
            content_type="image/png",
        )
    )

    assert sanitized != body
    assert Image.open(io.BytesIO(sanitized)).info.get("Comment") is None


def test_resolver_normalizes_identifier_type_case():
    registry = FixtureConnector().load_registry()
    index = ResolverIndex.from_registry(registry)
    identifier = registry.identifiers[0].model_copy(update={"type": registry.identifiers[0].type.upper()})
    candidate = registry.institutions[0]
    resolution = EntityResolver().resolve(
        type("Candidate", (), {
            "identifiers": [identifier],
            "domains": [],
            "legal_name": "unrelated",
            "country_code": candidate.country_code,
        })(),
        index,
    )

    assert resolution.action == "match"
    assert resolution.matched_id == identifier.owner_id


def test_identifier_rejects_naive_validity_timestamp():
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        Identifier(
            owner_id="inst_demo",
            type="bic",
            value="DEMOGB2L",
            source_id="src_demo",
            valid_to=datetime(2026, 8, 26),
        )


def test_withdrawal_rejects_non_utc_timestamp(tmp_path, demo_registry):
    manifest = ReleaseBuilder().build(
        demo_registry,
        "0.1.0",
        datetime(2026, 8, 26, tzinfo=timezone.utc),
        tmp_path / "release",
        generation_commit="test",
    )
    published = ReleaseLifecycle.promote(manifest, ReleaseStatus.PUBLISHED)

    with pytest.raises(ValueError, match="UTC"):
        ReleaseLifecycle.promote(
            published,
            ReleaseStatus.WITHDRAWN,
            reason="test",
            at=datetime(2026, 8, 26, tzinfo=timezone(timedelta(hours=5))),
        )


def test_release_input_digest_ignores_local_snapshot_path(tmp_path, demo_registry):
    other = demo_registry.model_copy(deep=True)
    other.source_runs[0].snapshot_path = "/machine-specific/path/snapshot.bin"
    first = ReleaseBuilder().build(
        demo_registry,
        "0.1.0",
        datetime(2026, 8, 26, tzinfo=timezone.utc),
        tmp_path / "first",
        generation_commit="test",
    )
    second = ReleaseBuilder().build(
        other,
        "0.1.0",
        datetime(2026, 8, 26, tzinfo=timezone.utc),
        tmp_path / "second",
        generation_commit="test",
    )

    assert first.input_sha256 == second.input_sha256


def test_release_rejects_existing_output_directory(tmp_path, demo_registry):
    output = tmp_path / "release"
    output.mkdir()
    sentinel = output / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(ReleaseValidationError, match="output"):
        ReleaseBuilder().build(
            demo_registry,
            "0.1.0",
            datetime(2026, 8, 26, tzinfo=timezone.utc),
            output,
            generation_commit="test",
        )
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_schema_manifest_matches_returned_manifest_and_avoids_self_hash(tmp_path, demo_registry):
    manifest = ReleaseBuilder().build(
        demo_registry,
        "0.1.0",
        datetime(2026, 8, 26, tzinfo=timezone.utc),
        tmp_path / "release",
        generation_commit="test",
    )
    disk = json.loads((tmp_path / "release" / "schema-version.json").read_text(encoding="utf-8"))

    assert disk == json.loads(manifest.model_dump_json(exclude_none=True))
    assert "schema-version.json" not in manifest.files
    checksum_lines = (tmp_path / "release" / "checksums.txt").read_text(encoding="utf-8").splitlines()
    assert any(line.endswith("  schema-version.json") for line in checksum_lines)


def test_registry_ci_enforces_documented_coverage_threshold():
    workflow_candidates = [
        Path(__file__).parents[1] / ".github" / "workflows" / "registry-core.yml",
        Path(__file__).parents[2] / ".github" / "workflows" / "registry-core.yml",
    ]
    workflow = next(path for path in workflow_candidates if path.exists())
    assert "--cov-fail-under=85" in workflow.read_text(encoding="utf-8")


def test_asset_policy_helpers_cover_malformed_and_unsupported_inputs():
    with pytest.raises(AssetPolicyError, match="external resource"):
        _raise_url_fetcher()
    compute_imagehash(_png_bytes())
    compute_imagehash(b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"><rect/></svg>')
    assert compute_imagehash(b"<svg>") is None
    assert compute_imagehash(b"not-an-image") is None
    with pytest.raises(AssetPolicyError, match="invalid raster"):
        AssetProcessor()._sanitize_and_normalize(
            FetchedAsset("https://example.test/a.jpg", "https://example.test/a.jpg", b"x", "image/jpeg")
        )
    with pytest.raises(AssetPolicyError, match="invalid SVG"):
        AssetProcessor()._sanitize_svg(b"<svg")
    with pytest.raises(AssetPolicyError, match="node"):
        AssetProcessor(max_svg_nodes=1)._sanitize_svg(b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>')


def test_svg_sanitizer_rejects_embeds_and_strips_event_handlers():
    with pytest.raises(AssetPolicyError, match="embedded"):
        AssetProcessor()._sanitize_svg(b'<svg xmlns="http://www.w3.org/2000/svg"><iframe/></svg>')
    sanitized = AssetProcessor()._sanitize_svg(b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><rect/></svg>')
    assert b"onload" not in sanitized
    with pytest.raises(AssetPolicyError, match="style"):
        AssetProcessor()._sanitize_svg(
            b'<svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:url(data:image/png;base64,x)"/></svg>'
        )


def test_raster_sanitizer_normalizes_webp_and_enforces_header_limits():
    image = Image.new("RGB", (2, 1), (255, 0, 0))
    encoded = io.BytesIO()
    image.save(encoded, format="WEBP", lossless=True)
    normalized = AssetProcessor()._sanitize_raster(encoded.getvalue(), "image/webp")
    assert normalized.startswith(b"RIFF")
    oversized = io.BytesIO()
    Image.new("RGB", (2, 1), (0, 0, 0)).save(oversized, format="PNG")
    with pytest.raises(AssetPolicyError, match="dimension"):
        AssetProcessor(max_dimension=1)._sanitize_raster(oversized.getvalue(), "image/png")


def test_source_url_validation_rejects_dns_failures_and_invalid_answers():
    with pytest.raises(UnsafeSourceUrl, match="DNS"):
        validate_source_url("https://example.test/logo.svg", resolver=lambda _host: (_ for _ in ()).throw(OSError("offline")))
    with pytest.raises(UnsafeSourceUrl, match="no address"):
        validate_source_url("https://example.test/logo.svg", resolver=lambda _host: [])
    with pytest.raises(UnsafeSourceUrl, match="invalid IP"):
        validate_source_url("https://example.test/logo.svg", resolver=lambda _host: ["not-an-ip"])


@pytest.mark.parametrize(
    "response",
    [httpx.Response(302), httpx.Response(500)],
)
def test_fetcher_rejects_missing_redirect_location_and_http_errors(response):
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: response))
    try:
        fetcher = SafeHttpxAssetFetcher(client, lambda _host: ["8.8.8.8"])
        with pytest.raises(AssetPolicyError):
            fetcher.fetch("https://example.test/logo.svg")
    finally:
        client.close()


def test_snapshot_store_rejects_root_symlinks_and_tampering(tmp_path):
    real_root = tmp_path / "real"
    real_root.mkdir()
    linked_root = tmp_path / "linked"
    linked_root.symlink_to(real_root, target_is_directory=True)
    with pytest.raises(ValueError, match="root"):
        FilesystemSnapshotStore(linked_root)

    store = FilesystemSnapshotStore(tmp_path / "snapshots")
    snapshot = store.put("src_demo", datetime(2026, 8, 26, tzinfo=timezone.utc), b"payload")
    Path(snapshot.path).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        store.read(snapshot)
    with pytest.raises(ValueError, match="UTC"):
        store.put("src_demo", datetime(2026, 8, 26), b"payload")
    with pytest.raises(ValueError, match="lowercase"):
        store.prune("src_demo", {"A" * 64})
    dynamic_root = tmp_path / "dynamic"
    dynamic_store = FilesystemSnapshotStore(dynamic_root)
    dynamic_root.symlink_to(real_root, target_is_directory=True)
    with pytest.raises(ValueError, match="root"):
        dynamic_store.prune("src_demo", set())


def test_release_validates_source_run_attestation_shape(demo_registry):
    run = demo_registry.source_runs[0].model_copy(update={"snapshot_sha256": "bad"})
    issues = ReleaseBuilder().validate(demo_registry.model_copy(update={"source_runs": [run]}), "test")
    assert any(issue.code == "invalid_snapshot_digest" for issue in issues)


def test_release_handles_naive_expiry_from_unvalidated_mutation(tmp_path, demo_registry):
    registry = demo_registry.model_copy(deep=True)
    asset = registry.assets[0]
    asset.rights_status = RightsStatus.LICENSED
    asset.permission_reference = "permit"
    asset.territories = ["GB"]
    asset.expires_at = datetime(2026, 8, 25)
    with pytest.raises(ReleaseValidationError, match="expires_at"):
        ReleaseBuilder().build(
            registry,
            "0.1.0",
            datetime(2026, 8, 26, tzinfo=timezone.utc),
            tmp_path / "release",
            generation_commit="test",
        )


def test_release_rejects_file_output_path(tmp_path, demo_registry):
    output = tmp_path / "release"
    output.write_text("keep", encoding="utf-8")
    with pytest.raises(ReleaseValidationError, match="output"):
        ReleaseBuilder().build(
            demo_registry,
            "0.1.0",
            datetime(2026, 8, 26, tzinfo=timezone.utc),
            output,
            generation_commit="test",
        )


def test_asset_processor_enforces_rights_and_size_guards():
    candidate = AssetCandidate(
        owner_id="inst_demo",
        variant="primary",
        source_id="src_demo",
        source_uri="https://example.test/logo.png",
        rights_status=RightsStatus.LICENSED,
    )
    with pytest.raises(AssetPolicyError, match="permission"):
        AssetProcessor(url_validator=lambda _url: _url).process(candidate, lambda _url: None)
    expired = candidate.model_copy(update={"permission_reference": "permit", "expires_at": datetime(2026, 8, 25, tzinfo=timezone.utc)})
    with pytest.raises(AssetPolicyError, match="expired"):
        AssetProcessor(url_validator=lambda _url: _url).process(expired, lambda _url: None)
    with pytest.raises(AssetPolicyError, match="SVG"):
        AssetProcessor(max_svg_bytes=1)._sanitize_svg(b"<svg/>")
    with pytest.raises(AssetPolicyError, match="asset body"):
        AssetProcessor(max_bytes=1, max_svg_bytes=100)._sanitize_svg(b"<svg/>")
    with pytest.raises(AssetPolicyError, match="raster"):
        AssetProcessor(max_bytes=1)._sanitize_raster(b"x")


def test_asset_processor_rejects_naive_rights_clock():
    candidate = AssetCandidate(
        owner_id="inst_demo",
        variant="primary",
        source_id="src_demo",
        source_uri="https://example.test/logo.png",
        rights_status=RightsStatus.REDISTRIBUTABLE,
    )
    with pytest.raises(AssetPolicyError, match="timezone"):
        AssetProcessor()._enforce_rights(candidate, datetime(2026, 8, 26))
    naive_expiry = candidate.model_copy(update={"expires_at": datetime(2026, 8, 25)})
    with pytest.raises(AssetPolicyError, match="expiry"):
        AssetProcessor()._enforce_rights(naive_expiry, datetime(2026, 8, 26, tzinfo=timezone.utc))


def test_fetcher_rejects_credentials_and_redirect_limit():
    with pytest.raises(UnsafeSourceUrl, match="credential"):
        validate_source_url("https://user:pass@example.test/logo.svg", resolver=lambda _host: ["8.8.8.8"])
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(302, headers={"location": "/again"})))
    try:
        with pytest.raises(AssetPolicyError, match="redirect limit"):
            SafeHttpxAssetFetcher(client, lambda _host: ["8.8.8.8"], max_redirects=0).fetch("https://example.test/logo.svg")
    finally:
        client.close()


def test_resolver_rejects_naive_reference_time():
    registry = FixtureConnector().load_registry()
    with pytest.raises(ValueError, match="UTC"):
        ResolverIndex.from_registry(registry, now=datetime(2026, 8, 26))
    bad_identifier = registry.identifiers[0].model_copy(update={"valid_to": datetime(2026, 8, 25)})
    bad_registry = registry.model_copy(update={"identifiers": [bad_identifier]})
    with pytest.raises(ValueError, match="valid_to"):
        ResolverIndex.from_registry(bad_registry)


def test_release_hash_helper_is_canonical():
    assert _hash_json({"b": 2, "a": 1}) == _hash_json({"a": 1, "b": 2})
