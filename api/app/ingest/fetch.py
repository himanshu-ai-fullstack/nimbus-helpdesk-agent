"""Fetch a web page to ingest, without letting a URL reach internal services.

A knowledge-base URL is untrusted input: without checks, "http://169.254.169.254/"
would read cloud metadata and "http://localhost:5432" would probe the database.
Every hop (including redirects) must resolve only to public addresses.

Known limit: the check resolves DNS before httpx connects, so a hostile DNS server
could answer differently the second time (DNS rebinding). Pinning the connection
to the checked IP would close that; it is out of scope for this demo."""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

MAX_REDIRECTS = 3
ALLOWED_TYPES = ("text/html", "text/plain", "text/markdown", "application/pdf")

Resolver = Callable[[str], Awaitable[list[str]]]


class FetchRejected(ValueError):
    pass


@dataclass
class Fetched:
    url: str
    content_type: str
    data: bytes


async def resolve(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip.split("%")[0])
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


async def check_url(url: str, resolver: Resolver = resolve) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise FetchRejected("only http and https URLs can be added")
    if not parts.hostname:
        raise FetchRejected("the URL has no host")
    if parts.username or parts.password:
        raise FetchRejected("URLs with credentials are not allowed")
    try:
        ips = await resolver(parts.hostname)
    except OSError as e:
        raise FetchRejected(f"couldn't resolve {parts.hostname}") from e
    if not ips or not all(is_public(ip) for ip in ips):
        raise FetchRejected(f"{parts.hostname} is not a public address")


async def fetch_url(
    url: str,
    *,
    max_bytes: int,
    timeout: float = 10.0,
    resolver: Resolver = resolve,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Fetched:
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        transport=transport,
        headers={"User-Agent": "HelpDeskAgent-KnowledgeIngest/1.0"},
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            await check_url(url, resolver)
            async with client.stream("GET", url) as resp:
                if resp.is_redirect:
                    url = urljoin(url, resp.headers.get("location", ""))
                    continue
                if resp.status_code >= 400:
                    raise FetchRejected(f"the page returned HTTP {resp.status_code}")
                content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                if content_type not in ALLOWED_TYPES:
                    raise FetchRejected(f"unsupported content type {content_type or '(none)'}")
                declared = int(resp.headers.get("content-length") or 0)
                if declared > max_bytes:
                    raise FetchRejected("the page is too large")
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) > max_bytes:
                        raise FetchRejected("the page is too large")
                return Fetched(url=str(resp.url), content_type=content_type, data=bytes(body))
    raise FetchRejected("too many redirects")
