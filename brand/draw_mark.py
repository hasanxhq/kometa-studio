#!/usr/bin/env python3
"""Draw the Starred poster masters in svg/ from their geometry.

    python draw_mark.py

Writes the marks, app icons and favicon as filled outlines (no strokes or transforms on shapes), so build_icons.py
can rasterise them, and prints the paths that are copied elsewhere: WORD_STAR into build_icons.py, and the mark into
frontend/src/components/Logo.tsx. Then run build_icons.py.
"""

import math
from pathlib import Path

SVG = Path(__file__).parent / "svg"

def f(n):
    s = f"{n:.2f}".rstrip("0").rstrip(".")
    return "0" if s == "-0" else s

def pt(p):
    return f"{f(p[0])} {f(p[1])}"

def capsule(a, b, w):
    """A line from a to b with round ends, as a filled outline."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    nx, ny = -dy / length * w / 2, dx / length * w / 2
    r = f(w / 2)
    p1, p2, p3, p4 = (a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny), (b[0] - nx, b[1] - ny), (a[0] - nx, a[1] - ny)
    return f"M{pt(p1)}L{pt(p2)}A{r} {r} 0 0 0 {pt(p3)}L{pt(p4)}A{r} {r} 0 0 0 {pt(p1)}Z"

def asterisk(cx, cy, radius, w):
    """Six arms: three lines through the centre."""
    out = []
    for angle in (90, 30, -30):
        t = math.radians(angle)
        dx, dy = math.cos(t) * radius, math.sin(t) * radius
        out.append(capsule((cx + dx, cy - dy), (cx - dx, cy + dy), w))
    return "".join(out)

def rounded_rect(x, y, w, h, r, angle=0.0, about=(0.0, 0.0)):
    t = math.radians(angle)
    def rot(p):
        px, py = p[0] - about[0], p[1] - about[1]
        return (about[0] + px * math.cos(t) - py * math.sin(t), about[1] + px * math.sin(t) + py * math.cos(t))
    R = f(r)
    arc = lambda p: f"A{R} {R} 0 0 1 {pt(rot(p))}"
    return (f"M{pt(rot((x + r, y)))}L{pt(rot((x + w - r, y)))}{arc((x + w, y + r))}L{pt(rot((x + w, y + h - r)))}{arc((x + w - r, y + h))}"
            f"L{pt(rot((x + r, y + h)))}{arc((x, y + h - r))}L{pt(rot((x, y + r)))}{arc((x + r, y))}Z")

# The mark, 64 x 64: three posters fanned from their bottom centre, the front one starred.
LEFT = rounded_rect(18, 10, 28, 42, 4, -15, (32, 54))
RIGHT = rounded_rect(18, 10, 28, 42, 4, 15, (32, 54))
FRONT = rounded_rect(18, 10, 28, 42, 4)
STAR = asterisk(32, 31, 8.5, 5)
# The star in the wordmark, 64 x 64.
WORD_STAR = asterisk(32, 32, 21, 12)
# The favicon, 16 x 16, on its own grid.
F_BACK = rounded_rect(4.5, 2, 7, 10.5, 1, 14, (8, 13.5))
F_STAR = asterisk(8, 7.25, 2.4, 1.5)

def mark(poster, ink, indent="  "):
    return (f'{indent}<path fill="{poster}" opacity="0.3" d="{LEFT}"/>\n{indent}<path fill="{poster}" opacity="0.55" d="{RIGHT}"/>\n'
            f'{indent}<path fill="{poster}" d="{FRONT}"/>\n{indent}<path fill="{ink}" d="{STAR}"/>\n')

head = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="Starr Studio">\n'
(SVG / "mark-on-dark.svg").write_text(head + mark("#f2b544", "#1a1406") + "</svg>\n")
(SVG / "mark-on-light.svg").write_text(head + mark("#b87a0a", "#1a1406") + "</svg>\n")
(SVG / "mark-mono.svg").write_text(
    head
    + f'  <path fill="currentColor" opacity="0.3" d="{LEFT}"/>\n  <path fill="currentColor" opacity="0.55" d="{RIGHT}"/>\n'
    + f'  <path fill="currentColor" d="{FRONT}"/>\n  <path fill="#3d3d3d" d="{STAR}"/>\n</svg>\n')
for name, rx, x, factor in (("icon-app.svg", ' rx="110"', 83.2, 5.4), ("icon-apple.svg", "", 83.2, 5.4), ("icon-maskable.svg", "", 115.2, 4.4)):
    (SVG / name).write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">\n  <rect width="512" height="512"{rx} fill="#0f1114"/>\n'
        f'  <g transform="translate({f(x)} {f(x)}) scale({f(factor)})" data-place="{f(x)} {f(x)} {f(factor)}">\n'
        + mark("#f2b544", "#1a1406", "    ") + "  </g>\n</svg>\n")
(SVG / "favicon.svg").write_text(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">\n  <rect width="16" height="16" rx="3" fill="#14171b"/>\n'
    f'  <path fill="#f2b544" opacity="0.45" d="{F_BACK}"/>\n  <rect x="4.5" y="2" width="7" height="10.5" rx="1" fill="#f2b544"/>\n'
    f'  <path fill="#1a1406" d="{F_STAR}"/>\n</svg>\n')
print("WORD_STAR =", WORD_STAR)
print("MARK =", {"left": LEFT, "right": RIGHT, "front": FRONT, "star": STAR})
