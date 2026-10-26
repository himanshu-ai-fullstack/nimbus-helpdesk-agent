import httpx
import pytest

from app.ingest import FetchRejected, UnsupportedDocument, fetch_url, parse_html, parse_upload
from app.ingest.fetch import check_url, is_public

from .fakes import make_pdf


def test_markdown_title_comes_from_heading():
    parsed = parse_upload("returns.md", b"# Returns policy\n\nThirty days.")
    assert parsed.title == "Returns policy" and parsed.pages[0].text.endswith("Thirty days.")
    assert parse_upload("store-hours.txt", b"Open 9 to 5.").title == "Store hours"


def test_pdf_pages_keep_their_numbers():
    parsed = parse_upload("manual.pdf", make_pdf(["Charging the robot", "Resetting the arm"]))
    assert [(p.number, p.text) for p in parsed.pages] == [
        (1, "Charging the robot"),
        (2, "Resetting the arm"),
    ]


def test_pdf_without_text_is_rejected():
    with pytest.raises(UnsupportedDocument, match="no extractable text"):
        parse_upload("scan.pdf", make_pdf([""]))
    with pytest.raises(UnsupportedDocument, match="couldn't read"):
        parse_upload("broken.pdf", b"%PDF-1.4 not really")


def test_unsupported_types_and_encodings():
    with pytest.raises(UnsupportedDocument, match="unsupported file type .exe"):
        parse_upload("setup.exe", b"MZ")
    with pytest.raises(UnsupportedDocument, match="UTF-8"):
        parse_upload("notes.txt", "café".encode("latin-1"))


def test_html_keeps_main_content_only():
    html = b"""<html><head><title>Shipping FAQ</title><script>track()</script></head>
    <body><nav>Home | Shop</nav><main><h1>Shipping</h1><p>We ship in 4 days.</p></main>
    <footer>(c) Cartwheel</footer></body></html>"""
    parsed = parse_html(html, "https://example.com/faq")
    assert parsed.title == "Shipping FAQ"
    assert parsed.pages[0].text == "Shipping\nWe ship in 4 days."


@pytest.mark.parametrize(
    "ip, public",
    [
        ("93.184.216.34", True),
        ("127.0.0.1", False),
        ("10.0.0.5", False),
        ("192.168.1.1", False),
        ("169.254.169.254", False),  # cloud metadata
        ("::1", False),
        ("::ffff:127.0.0.1", False),
        ("fd00::1", False),
        ("0.0.0.0", False),
    ],
)
def test_public_address_check(ip, public):
    assert is_public(ip) is public


def resolver(mapping):
    async def resolve(host):
        return mapping[host]

    return resolve


@pytest.mark.parametrize(
    "url, message",
    [
        ("ftp://example.com/x", "only http and https"),
        ("http://user:pw@example.com/", "credentials"),
        ("http://internal.example/", "not a public address"),
        ("http://mixed.example/", "not a public address"),
    ],
)
async def test_unsafe_urls_are_rejected(url, message):
    resolve = resolver(
        {
            "example.com": ["93.184.216.34"],
            "internal.example": ["10.1.2.3"],
            "mixed.example": ["93.184.216.34", "127.0.0.1"],
        }
    )
    with pytest.raises(FetchRejected, match=message):
        await check_url(url, resolve)


async def test_localhost_is_rejected_with_real_dns():
    with pytest.raises(FetchRejected, match="not a public address"):
        await check_url("http://localhost:5432/")


def transport(routes):
    def handler(request: httpx.Request) -> httpx.Response:
        return routes[str(request.url)]

    return httpx.MockTransport(handler)


async def test_fetch_follows_safe_redirects_and_returns_the_page():
    routes = {
        "https://docs.example/start": httpx.Response(
            301, headers={"location": "https://docs.example/faq"}
        ),
        "https://docs.example/faq": httpx.Response(
            200, headers={"content-type": "text/html; charset=utf-8"}, content=b"<p>hi</p>"
        ),
    }
    page = await fetch_url(
        "https://docs.example/start",
        max_bytes=1000,
        resolver=resolver({"docs.example": ["93.184.216.34"]}),
        transport=transport(routes),
    )
    assert page.url == "https://docs.example/faq" and page.data == b"<p>hi</p>"


async def test_redirect_to_an_internal_host_is_rejected():
    routes = {
        "https://docs.example/start": httpx.Response(
            302, headers={"location": "http://metadata.internal/latest"}
        )
    }
    with pytest.raises(FetchRejected, match="metadata.internal is not a public address"):
        await fetch_url(
            "https://docs.example/start",
            max_bytes=1000,
            resolver=resolver(
                {"docs.example": ["93.184.216.34"], "metadata.internal": ["169.254.169.254"]}
            ),
            transport=transport(routes),
        )


@pytest.mark.parametrize(
    "response, message",
    [
        (httpx.Response(200, headers={"content-type": "image/png"}, content=b"x"), "content type"),
        (
            httpx.Response(200, headers={"content-type": "text/plain"}, content=b"x" * 2000),
            "too large",
        ),
        (httpx.Response(404, headers={"content-type": "text/html"}), "HTTP 404"),
    ],
)
async def test_fetch_rejects_bad_responses(response, message):
    with pytest.raises(FetchRejected, match=message):
        await fetch_url(
            "https://docs.example/x",
            max_bytes=1000,
            resolver=resolver({"docs.example": ["93.184.216.34"]}),
            transport=transport({"https://docs.example/x": response}),
        )
