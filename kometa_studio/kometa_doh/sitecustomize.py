"""Kometa Studio's network settings for Kometa's Python (network.py), loaded by Python itself when Studio
puts this folder on PYTHONPATH.

``socket.getaddrinfo`` answers the hosts in STUDIO_DOH_HOSTS (and their subdomains) through DNS over HTTPS
at STUDIO_DOH_URL; if that lookup fails, the system's resolver is tried after all. With STUDIO_PREFER_IPV4
set, IPv4 addresses come first for every name. Standard library only: this runs inside Kometa's own Python.
"""

import json
import os
import socket
import threading
import time
import urllib.parse
import urllib.request

_HOSTS = tuple(h.strip().lower() for h in os.environ.get("STUDIO_DOH_HOSTS", "").split(",") if h.strip())
_URL = os.environ.get("STUDIO_DOH_URL", "https://1.1.1.1/dns-query")
_original = socket.getaddrinfo
_cache: dict[str, tuple[float, list[str]]] = {}
_lock = threading.Lock()


def _covered(host: str) -> bool:
    host = host.lower().rstrip(".")
    return any(host == suffix or host.endswith("." + suffix) for suffix in _HOSTS)


def _lookup(host: str) -> list[str]:
    with _lock:
        cached = _cache.get(host)
        if cached and cached[0] > time.monotonic():
            return cached[1]
    query = urllib.parse.urlencode({"name": host, "type": "A"})
    request = urllib.request.Request(f"{_URL}?{query}", headers={"Accept": "application/dns-json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.load(response)
    answers = [a for a in data.get("Answer") or [] if isinstance(a, dict) and a.get("type") == 1 and a.get("data")]
    addresses = [str(a["data"]) for a in answers]
    if addresses:
        ttl = min(int(a.get("TTL", 300)) for a in answers)
        with _lock:
            _cache[host] = (time.monotonic() + max(ttl, 30), addresses)
    return addresses


_IPV4_FIRST = bool(os.environ.get("STUDIO_PREFER_IPV4"))


def getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if isinstance(host, bytes):
        name = host.decode("ascii", "ignore")
    else:
        name = host
    if _HOSTS and isinstance(name, str) and _covered(name) and family in (0, socket.AF_INET, socket.AF_UNSPEC):
        try:
            addresses = _lookup(name)
        except Exception:
            addresses = []
        if addresses:
            results = []
            for address in addresses:
                results += _original(address, port, socket.AF_INET, type, proto, flags | socket.AI_NUMERICHOST)
            return results
    results = _original(host, port, family, type, proto, flags)
    if _IPV4_FIRST:
        results = sorted(results, key=lambda info: info[0] != socket.AF_INET)
    return results


if _HOSTS or _IPV4_FIRST:
    socket.getaddrinfo = getaddrinfo
