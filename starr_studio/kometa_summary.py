"""What Kometa's end-of-run summary says about each collection it didn't build.

Kometa refuses some collections only when it builds them (``collection_order: custom`` with a ``tmdb_collection``, for
one), still exits 0, and sends no webhook for it. Its summary table names the collection and the reason::

    |=========== Movies Summary ===========|
    |          Title          |   +   |   =   |   -   | Run Time | Status                    |
    | Harry Potter Collection |     0 |     0 |     0 |  0:00:00 | Builder Validation Error  |
    | Collection Error: collection_order: custom cannot be used with tmdb_collection          |

Studio reads that from the run's own output (data/runs/<id>.log), so a collection that didn't appear in Plex says why.
"""

import re
from pathlib import Path

SECTION = re.compile(r"^\|=+ (?P<library>.+?) Summary =+\|$")
ROW = re.compile(r"^\| (?P<title>.+?)\s+\|\s+\d+\s+\|\s+\d+\s+\|\s+\d+\s+\|\s+[\d:]+\s+\| (?P<status>.+?)\s*\|$")
ERROR = re.compile(r"^\| (?P<message>[A-Za-z ]*Error: .+?)\s*\|$")


def collection_errors(text: str) -> dict[tuple[str, str], str]:
    """{(library, title casefolded): why} for collections the summary marks with an error."""
    found: dict[tuple[str, str], str] = {}
    library = ""
    current: tuple[str, str] | None = None
    for line in text.splitlines():
        line = line.rstrip()
        if section := SECTION.match(line):
            library, current = section["library"].strip(), None
            continue
        if row := ROW.match(line):
            current = (library, row["title"].strip().casefold())
            if "error" in row["status"].lower():
                found[current] = row["status"].strip()
            continue
        if current and (error := ERROR.match(line)):
            found[current] = error["message"].strip()  # the reason, under its row, beats the bare status
            continue
        current = None  # an error line only ever sits right under its collection's row
    return found


def read_errors(path: Path) -> dict[tuple[str, str], str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    return collection_errors(text)
