"""A small line-based three-way merge, used to keep a file's own formatting when Studio edits it.

``base`` is the file after an unedited ruamel load and save, ``ours`` the file as the user wrote
it, ``theirs`` ruamel's output with Studio's change. base→ours is the user's formatting and
base→theirs is the change; if they touch different lines, both apply. Overlapping changes, or an
insertion where the other side changed, count as a conflict (None), and the caller falls back to
ruamel's output.
"""

from difflib import SequenceMatcher

Hunk = tuple[int, int, list[str]]  # replace base[start:end] with these lines


def _hunks(base: list[str], other: list[str]) -> list[Hunk]:
    matcher = SequenceMatcher(None, base, other, autojunk=False)
    return [(i1, i2, other[j1:j2]) for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != "equal"]


def _clash(a: Hunk, b: Hunk) -> bool:
    """Whether two hunks can't both apply: replaced ranges that overlap, or an insertion at or inside the other's range."""
    if a[0] < a[1] and b[0] < b[1]:
        return a[0] < b[1] and b[0] < a[1]  # replacements that only touch are fine
    return a[0] <= b[1] and b[0] <= a[1]


def merge3(base: str, ours: str, theirs: str) -> str | None:
    base_lines = base.splitlines(keepends=True)
    ours_hunks = _hunks(base_lines, ours.splitlines(keepends=True))
    theirs_hunks = _hunks(base_lines, theirs.splitlines(keepends=True))
    if any(_clash(a, b) for a in ours_hunks for b in theirs_hunks):
        return None
    merged: list[str] = []
    position = 0
    for start, end, lines in sorted(ours_hunks + theirs_hunks, key=lambda hunk: (hunk[0], hunk[1])):
        merged += base_lines[position:start]
        merged += lines
        position = end
    merged += base_lines[position:]
    return "".join(merged)
