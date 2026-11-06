"""Keep secrets that travel in a URL out of the access log.

Kometa's webhooks and Radarr/Sonarr's reach Studio as ``…/events?token=<secret>``: the token has to be in the URL,
because that's all those apps let you configure. uvicorn's access log prints each request's path and query, so without
this every Kometa run wrote the token into Studio's log (docker logs, journald). This blanks those values in it.
"""

import logging
import re

SECRET_QUERY = re.compile(r"(?P<name>(?:^|[?&])(?:token|api_?key|x-plex-token)=)[^&\s#]*", re.IGNORECASE)
HIDDEN = "<hidden>"


def redact(text: str) -> str:
    return SECRET_QUERY.sub(lambda match: match["name"] + HIDDEN, text)


class RedactQuerySecrets(logging.Filter):
    """For uvicorn.access: its args are (client, method, path with query, HTTP version, status)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) >= 3 and isinstance(record.args[2], str):
            args = list(record.args)
            args[2] = redact(args[2])
            record.args = tuple(args)
        return True


def install() -> None:
    """Once per process; uvicorn has configured its loggers by the time the app starts."""
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(existing, RedactQuerySecrets) for existing in access.filters):
        access.addFilter(RedactQuerySecrets())
