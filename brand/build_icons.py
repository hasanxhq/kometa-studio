#!/usr/bin/env python3
"""Rebuild the logo's PNGs, ICO and lockups from the SVGs in svg/.

    python build_icons.py [path/to/SpaceGrotesk-SemiBold.ttf]

Icons need Pillow and fontTools. The font is optional: with it, the lockups are redrawn too, as outlines,
which also needs uharfbuzz for Space Grotesk's kerning. Fonts aren't kept in this repository.
"""

import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from fontTools.pens.recordingPen import RecordingPen
from fontTools.svgLib.path import parse_path
from PIL import Image, ImageColor, ImageDraw

HERE = Path(__file__).parent
SVG = HERE / "svg"
PUBLIC = HERE.parent / "frontend" / "public"
OVERSAMPLE = 16  # whole-pixel edges stay sharp when scaled down by a box filter
NS = "{http://www.w3.org/2000/svg}"

K = "M14.5 10H22.5A1.5 1.5 0 0 1 24 11.5V37.5L50 54H36L24 45V52.5A1.5 1.5 0 0 1 22.5 54H14.5A1.5 1.5 0 0 1 13 52.5V11.5A1.5 1.5 0 0 1 14.5 10Z"
COMET = "M24 35L40.35 10.55A8 8 0 1 1 50.48 22.2Z"
# The lockup's proportions, from the logo canvas: a 44 px mark, 30 px type, a 12 px gap.
MARK, TYPE, GAP = 44, 30, 12
LOCKUPS = {"lockup-on-dark.svg": ("#ecedee", "#f2b544", "#ecedee", "#f2b544"), "lockup-on-light.svg": ("#1a1406", "#b87a0a", "#1a1406", "#8a5a00")}


def flatten(d: str) -> list[list[tuple[float, float]]]:
    """A path as polygons: curves become short straight lines, far finer than a pixel."""
    pen = RecordingPen()
    parse_path(d, pen)
    polygons, points = [], []
    for operator, args in pen.value:
        if operator == "moveTo":
            points = [args[0]]
            polygons.append(points)
        elif operator == "lineTo":
            points.append(args[0])
        elif operator == "curveTo":
            start = points[-1]
            for step in range(1, 65):
                t, u = step / 64, 1 - step / 64
                points.append(tuple(u**3 * a + 3 * u * u * t * b + 3 * u * t * t * c + t**3 * e for a, b, c, e in zip(start, *args)))
    return polygons


def render(source: Path, size: int) -> Image.Image:
    root = ET.parse(source).getroot()
    _, _, width, _ = (float(n) for n in root.attrib["viewBox"].split())
    canvas = size * OVERSAMPLE
    scale = canvas / width
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))

    def draw(element: ET.Element, shift: tuple[float, float], zoom: float) -> None:
        if element.tag == f"{NS}g":
            x, y, factor = (float(n) for n in element.attrib["data-place"].split())
            for child in element:
                draw(child, (shift[0] + x * zoom, shift[1] + y * zoom), zoom * factor)
            return
        fill = ImageColor.getrgb(element.attrib["fill"]) + (255,)
        mask = Image.new("L", (canvas, canvas), 0)
        pencil = ImageDraw.Draw(mask)
        if element.tag == f"{NS}rect":
            x, y, w, h = (float(element.attrib.get(k, 0)) * zoom for k in ("x", "y", "width", "height"))
            box = (shift[0] + x, shift[1] + y, shift[0] + x + w - 1, shift[1] + y + h - 1)
            pencil.rounded_rectangle(box, float(element.attrib.get("rx", 0)) * zoom, fill=255)
        elif element.tag == f"{NS}path":
            for polygon in flatten(element.attrib["d"]):
                pencil.polygon([(shift[0] + px * zoom, shift[1] + py * zoom) for px, py in polygon], fill=255)
        image.paste(fill, (0, 0), mask)

    for element in root:
        draw(element, (0.0, 0.0), scale)
    return image.resize((size, size), Image.Resampling.BOX)


def icons() -> None:
    PUBLIC.mkdir(exist_ok=True)
    shutil.copy(SVG / "favicon.svg", PUBLIC / "favicon.svg")
    for name, size, source in (
        ("apple-touch-icon.png", 180, "icon-apple.svg"),
        ("icon-192.png", 192, "icon-app.svg"),
        ("icon-512.png", 512, "icon-app.svg"),
        ("icon-maskable-512.png", 512, "icon-maskable.svg"),
    ):
        render(SVG / source, size).save(PUBLIC / name, optimize=True)
    small, *larger = [render(SVG / "favicon.svg", size) for size in (16, 32, 48)]
    small.save(PUBLIC / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)], append_images=larger)


def lockups(font_path: Path) -> None:
    import uharfbuzz as hb
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.ttLib import TTFont

    font = TTFont(font_path)
    glyphs, order = font.getGlyphSet(), font.getGlyphOrder()
    em = font["head"].unitsPerEm
    scale = TYPE / em
    face = hb.Font(hb.Face(font_path.read_bytes()))
    text = "Kometa Studio"
    buffer = hb.Buffer()
    buffer.add_str(text)
    buffer.guess_segment_properties()
    hb.shape(face, buffer, {"kern": True, "liga": True})

    # The mark's own edges, not its 64-unit box, set the left edge and the height.
    points = [point for d in (K, COMET) for polygon in flatten(d) for point in polygon]
    zoom = MARK / 64
    left, right = min(x for x, _ in points) * zoom, max(x for x, _ in points) * zoom
    top, bottom = min(y for _, y in points) * zoom, max(y for _, y in points) * zoom
    cap = font["OS/2"].sCapHeight * scale
    baseline = (top + bottom) / 2 + cap / 2  # the words sit level with the mark's middle
    origin = 44 + GAP  # where the canvas's 44 px mark box ends, plus the gap

    paths = {False: [], True: []}
    pen_x = 0
    for info, position in zip(buffer.glyph_infos, buffer.glyph_positions):
        pen = SVGPathPen(glyphs, ntos=lambda n: f"{n:.2f}".rstrip("0").rstrip("."))
        x = origin + (pen_x + position.x_offset) * scale
        glyphs[order[info.codepoint]].draw(TransformPen(pen, (scale, 0, 0, -scale, x, baseline)))
        if commands := pen.getCommands():
            paths[info.cluster >= text.index("Studio")].append(commands)
        pen_x += position.x_advance
    end = origin + pen_x * scale
    width, height = end - left, bottom - top

    for name, (k, comet, word, accent) in LOCKUPS.items():
        (SVG / name).write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{left:.2f} {top:.2f} {width:.2f} {height:.2f}" width="{width * 2:.0f}" height="{height * 2:.0f}" role="img" aria-label="Kometa Studio">\n'
            f'  <g transform="scale({zoom})">\n    <path fill="{k}" d="{K}"/>\n    <path fill="{comet}" d="{COMET}"/>\n  </g>\n'
            f'  <path fill="{word}" d="{"".join(paths[False])}"/>\n  <path fill="{accent}" d="{"".join(paths[True])}"/>\n</svg>\n',
            encoding="utf-8",
        )


if __name__ == "__main__":
    icons()
    if len(sys.argv) > 1:
        lockups(Path(sys.argv[1]))
