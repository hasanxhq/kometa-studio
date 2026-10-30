import asyncio

import httpx
import pytest
from fakeplex import RELAY_URI, REMOTE_URI, RESOURCES_XML, SERVER_TOKEN, FakePlex

from kometa_studio import plex
from kometa_studio.plex import Candidate, Pin, Probe


def run(awaitable):
    return asyncio.run(awaitable)


async def with_client(fake: FakePlex, call):
    async with httpx.AsyncClient(transport=fake.transport()) as client:
        return await call(client)


def test_only_owned_servers_are_kept():
    servers = plex.parse_resources(RESOURCES_XML)
    assert [(s.id, s.name, s.token, s.version) for s in servers] == [("srv1", "Seedbox", "srv-token", "1.41.2.9200")]


def test_connections_expand_to_plex_direct_and_plain_ip():
    [server] = plex.parse_resources(RESOURCES_XML)
    assert server.candidates == [
        Candidate("https://172-17-0-2.abc123.plex.direct:32400", local=True, relay=False),
        Candidate("http://172.17.0.2:32400", local=True, relay=False),
        Candidate(REMOTE_URI, local=False, relay=False),
        Candidate("http://203.0.113.7:32400", local=False, relay=False),
        Candidate(RELAY_URI, local=False, relay=True),  # a relay has no plain-IP twin
    ]


def test_ipv6_addresses_are_bracketed():
    [candidate] = [c for c in plex.expand_connections([("", "2001:db8::1", "32400", False, False)])]
    assert candidate.uri == "http://[2001:db8::1]:32400"


def test_unreadable_resources_are_reported():
    with pytest.raises(plex.PlexError, match="can't read"):
        plex.parse_resources("<html>Cloudflare</html")


def test_ranking_prefers_working_local_https_and_puts_relay_last():
    def probe(uri, ok=True, local=False, relay=False, ms=50):
        return Probe(Candidate(uri, local, relay), ok, None if ok else "failed", ms if ok else None)

    ranked = plex.rank(
        [
            probe("https://relay", relay=True, ms=5),
            probe("http://remote-ip", ms=10),
            probe("https://local-down", ok=False, local=True),
            probe("https://remote", ms=80),
            probe("http://local-ip", local=True, ms=30),
            probe("https://local", local=True, ms=40),
        ]
    )
    assert [p.candidate.uri for p in ranked] == [
        "https://local",
        "http://local-ip",
        "https://remote",
        "http://remote-ip",
        "https://relay",
        "https://local-down",
    ]


def test_probing_a_server_from_outside_the_seedbox():
    [server] = plex.parse_resources(RESOURCES_XML)
    probes = run(with_client(FakePlex(), lambda client: plex.probe_server(client, server)))
    assert [(p.candidate.uri, p.ok) for p in probes[:2]] == [(REMOTE_URI, True), (RELAY_URI, True)]
    assert all(not p.ok and "Can't connect" in p.error for p in probes[2:])


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(401), "rejected the token"),
        (httpx.Response(500), "HTTP 500"),
        (httpx.Response(200, text="<html>router login</html>"), "isn't a Plex Media Server"),
        (httpx.Response(200, json={"MediaContainer": {"machineIdentifier": "other", "friendlyName": "Nope"}}), "different Plex server"),
    ],
)
def test_probe_explains_failures(response, message):
    async def call(client):
        return await plex.probe(client, "http://server:32400", SERVER_TOKEN, expected_id="srv1")

    transport = httpx.MockTransport(lambda request: response)
    with pytest.raises(plex.PlexError, match=message):
        run(_with_transport(transport, call))


def test_probe_timeout_is_explained():
    def slow(request):
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(plex.PlexError, match="No answer within 5 s"):
        run(_with_transport(httpx.MockTransport(slow), lambda c: plex.probe(c, "http://server:32400", "t")))


async def _with_transport(transport, call):
    async with httpx.AsyncClient(transport=transport) as client:
        return await call(client)


def test_pin_flow():
    fake = FakePlex()

    async def flow(client):
        pin = await plex.create_pin(client, "studio-id")
        waiting = await plex.check_pin(client, "studio-id", pin.id)
        fake.pin_approved = True
        token = await plex.check_pin(client, "studio-id", pin.id)
        return pin, waiting, token

    pin, waiting, token = run(with_client(fake, flow))
    assert pin == Pin(42, "abcd1234")
    assert waiting is None
    assert token == "acct-token"
    assert fake.requests[0].url.params["strong"] == "true"
    assert fake.requests[0].headers["X-Plex-Product"] == "Kometa Studio"


def test_expired_pin():
    fake = FakePlex()
    fake.pin_expired = True
    with pytest.raises(plex.PinExpired):
        run(with_client(fake, lambda client: plex.check_pin(client, "studio-id", 42)))


def test_auth_url_carries_client_id_and_code():
    url = plex.auth_url("studio-id", Pin(42, "abcd1234"))
    assert url.startswith("https://app.plex.tv/auth/#!?")
    assert "clientID=studio-id" in url
    assert "code=abcd1234" in url
    assert "context%5Bdevice%5D%5Bproduct%5D=Kometa+Studio" in url


def test_revoked_account_token():
    fake = FakePlex()
    fake.account_token = "something-else"
    with pytest.raises(plex.TokenRejected):
        run(with_client(fake, lambda client: plex.fetch_servers(client, "studio-id", "acct-token")))


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        (" https://plex.example.com/ ", "https://plex.example.com"),
        ("http://10.0.0.5:32400", "http://10.0.0.5:32400"),
        ("https://seedbox.example.com/plex", "https://seedbox.example.com/plex"),
    ],
)
def test_typed_urls_are_tidied(typed, expected):
    assert plex.normalise_url(typed) == expected


@pytest.mark.parametrize(
    "typed", ["10.0.0.5:32400", "ftp://server", "https://app.plex.tv/desktop", "http://server:32400/?X-Plex-Token=abc"]
)
def test_bad_typed_urls_are_refused(typed):
    with pytest.raises(ValueError):
        plex.normalise_url(typed)
