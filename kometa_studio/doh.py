"""DNS over HTTPS lookups, for Settings → Network's DoH and its connection check (network.py).

``get`` connects to the address DoH gives, sending the real name for TLS (SNI) and in the Host header,
so the certificate is still checked against that name.
"""

from urllib.parse import urlsplit, urlunsplit

import httpx

DOH_URL = "https://1.1.1.1/dns-query"
TIMEOUT = 10.0


class DohProblem(Exception):
    pass


async def resolve(http: httpx.AsyncClient, host: str, url: str = DOH_URL) -> str:
    """The first IPv4 address DoH (``url``: 1.1.1.1 unless another provider's) gives for ``host``."""
    return (await resolve_all(http, host, url))[0]


async def resolve_all(http: httpx.AsyncClient, host: str, url: str = DOH_URL) -> list[str]:
    """Every IPv4 address DoH gives for ``host``, in its order."""
    provider = urlsplit(url).hostname
    try:
        response = await http.get(url, params={"name": host, "type": "A"}, headers={"Accept": "application/dns-json"}, timeout=TIMEOUT)
        if response.status_code != 200:
            raise DohProblem(f"{provider} answered HTTP {response.status_code} when looking up {host}")
        answers = response.json().get("Answer") or []
    except (httpx.HTTPError, ValueError, AttributeError) as error:
        raise DohProblem(f"Couldn't look up {host} over DNS over HTTPS ({provider}): {error}") from None
    found = [str(answer["data"]) for answer in answers if isinstance(answer, dict) and answer.get("type") == 1 and answer.get("data")]
    if not found:
        raise DohProblem(f"{provider} has no address for {host}")
    return found


async def get(http: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
    """GET ``url``, its host looked up over DoH: connect to that address, with the real name for TLS and Host.

    If an address can't be connected to (some networks reset a few of a CDN's addresses), the next one is tried.
    """
    parts = urlsplit(url)
    host = parts.hostname or ""
    headers = dict(kwargs.pop("headers", None) or {}) | {"Host": parts.netloc}
    failed: httpx.TransportError | None = None
    for address in await resolve_all(http, host):
        netloc = address + (f":{parts.port}" if parts.port else "")
        try:
            return await http.get(urlunsplit(parts._replace(netloc=netloc)), headers=headers, extensions={"sni_hostname": host}, **kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout) as error:
            failed = error
    raise failed  # type: ignore[misc]
