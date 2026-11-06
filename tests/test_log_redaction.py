"""Webhook tokens and API keys in a URL never reach the access log."""

import logging

from starr_studio.log_redaction import RedactQuerySecrets, install, redact


def test_redact_hides_secret_query_values_only():
    assert redact("/api/v1/kometa/events?token=not-a-real-token-0001") == "/api/v1/kometa/events?token=<hidden>"
    assert redact("/api/v1/arr/events?kind=radarr&token=abc&x=1") == "/api/v1/arr/events?kind=radarr&token=<hidden>&x=1"
    assert redact("/x?apikey=1&api_key=2&X-Plex-Token=3") == "/x?apikey=<hidden>&api_key=<hidden>&X-Plex-Token=<hidden>"
    assert redact("/api/v1/requests?status=failed") == "/api/v1/requests?status=failed"
    assert redact("/api/v1/tokens?mytoken=1") == "/api/v1/tokens?mytoken=1"  # only whole parameter names


def test_the_access_log_line_is_redacted(caplog):
    install()
    install()  # once is enough
    access = logging.getLogger("uvicorn.access")
    assert sum(isinstance(f, RedactQuerySecrets) for f in access.filters) == 1
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        access.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "POST", "/api/v1/kometa/events?token=secret123", "1.1", 200)
    assert "secret123" not in caplog.text
    assert "token=<hidden>" in caplog.text
