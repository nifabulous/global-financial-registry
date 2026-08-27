import httpx
import pytest

from financial_registry.fetch_policy import (
    AssetPolicyError,
    SafeHttpxAssetFetcher,
    SafeHttpxHtmlFetcher,
    UnsafeSourceUrl,
    validate_source_url,
)


def test_source_url_requires_https():
    with pytest.raises(UnsafeSourceUrl):
        validate_source_url("http://example.test/logo.svg")


def test_source_url_rejects_loopback_resolution():
    with pytest.raises(UnsafeSourceUrl):
        validate_source_url("https://localhost/logo.svg", resolver=lambda host: ["127.0.0.1"])


@pytest.mark.parametrize("address", ["127.0.0.1", "::ffff:127.0.0.1", "169.254.1.1"])
def test_source_url_rejects_private_and_mapped_addresses(address):
    with pytest.raises(UnsafeSourceUrl):
        validate_source_url("https://public.test/logo.svg", resolver=lambda host: [address])


def test_fetcher_revalidates_redirect_destination():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(302, headers={"location": "https://private.test/logo.svg"})
    )
    client = httpx.Client(transport=transport)
    fetcher = SafeHttpxAssetFetcher(
        client=client,
        resolver=lambda host: ["127.0.0.1"] if host == "private.test" else ["8.8.8.8"],
    )
    with pytest.raises(UnsafeSourceUrl):
        fetcher.fetch("https://public.test/logo.svg")


def test_fetcher_rejects_body_over_limit():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": "image/svg+xml"}, content=b"x" * 32)
    )
    client = httpx.Client(transport=transport)
    fetcher = SafeHttpxAssetFetcher(
        client=client,
        resolver=lambda host: ["8.8.8.8"],
        max_bytes=16,
    )
    with pytest.raises(AssetPolicyError, match="size"):
        fetcher.fetch("https://public.test/logo.svg")


def test_fetcher_rejects_ambiguous_content_type():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"not-an-image"))
    fetcher = SafeHttpxAssetFetcher(
        client=httpx.Client(transport=transport),
        resolver=lambda host: ["8.8.8.8"],
    )
    with pytest.raises(AssetPolicyError, match="content type"):
        fetcher.fetch("https://public.test/logo.svg")


def test_fetcher_accepts_jpeg_content_type():
    fetcher = SafeHttpxAssetFetcher(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    headers={"content-type": "image/jpeg"},
                    content=b"jpeg",
                )
            )
        ),
        resolver=lambda host: ["8.8.8.8"],
    )

    try:
        fetched = fetcher.fetch("https://public.test/logo.jpg")
    finally:
        fetcher.client.close()

    assert fetched.content_type == "image/jpeg"


def test_html_fetcher_pins_dns_and_returns_decoded_html():
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=b'<link rel="icon" href="/logo.svg">',
        )

    client = httpx.Client(transport=httpx.MockTransport(transport))
    try:
        fetched = SafeHttpxHtmlFetcher(client, lambda _host: ["8.8.8.8"]).fetch(
            "https://public.test/"
        )
    finally:
        client.close()

    assert requests[0].url.host == "8.8.8.8"
    assert requests[0].headers["host"] == "public.test"
    assert fetched.final_url == "https://public.test/"
    assert fetched.content_type == "text/html"
    assert '<link rel="icon"' in fetched.body


def test_html_fetcher_rejects_non_html_content_type():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, headers={"content-type": "image/svg+xml"}, content=b"<svg/>")
        )
    )
    try:
        fetcher = SafeHttpxHtmlFetcher(client, lambda _host: ["8.8.8.8"])
        with pytest.raises(AssetPolicyError, match="content type"):
            fetcher.fetch("https://public.test/")
    finally:
        client.close()


def test_html_fetcher_enforces_html_size_limit():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b"x" * 32,
            )
        )
    )
    try:
        fetcher = SafeHttpxHtmlFetcher(client, lambda _host: ["8.8.8.8"], max_bytes=16)
        with pytest.raises(AssetPolicyError, match="size"):
            fetcher.fetch("https://public.test/")
    finally:
        client.close()
