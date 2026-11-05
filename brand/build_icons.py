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

# The star in "St*arr", on a 64-unit grid: six round-ended arms. In the words it is 0.46 em tall, its foot 0.26 em above
# the baseline (raised, like an asterisk), with 0.03 em on each side.
WORD_STAR = "M26 11L26 53A6 6 0 0 0 38 53L38 11A6 6 0 0 0 26 11ZM47.19 16.3L10.81 37.3A6 6 0 0 0 16.81 47.7L53.19 26.7A6 6 0 0 0 47.19 16.3ZM53.19 37.3L16.81 16.3A6 6 0 0 0 10.81 26.7L47.19 47.7A6 6 0 0 0 53.19 37.3Z"
STAR_SIZE, STAR_LIFT, STAR_SIDE = 0.46, 0.26, 0.03
# The lockup's proportions, from the logo canvas: a 44 px mark, 30 px type, a 12 px gap.
MARK, TYPE, GAP = 44, 30, 12
# Lockup file: (the mark it uses, words, "Studio", the star)
LOCKUPS = {
    "lockup-on-dark.svg": ("mark-on-dark.svg", "#ecedee", "#f2b544", "#f2b544"),
    "lockup-on-light.svg": ("mark-on-light.svg", "#1a1406", "#8a5a00", "#b87a0a"),
}


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
        fill = ImageColor.getrgb(element.attrib["fill"]) + (round(255 * float(element.attrib.get("opacity", 1))),)
        mask = Image.new("L", (canvas, canvas), 0)
        pencil = ImageDraw.Draw(mask)
        if element.tag == f"{NS}rect":
            x, y, w, h = (float(element.attrib.get(k, 0)) * zoom for k in ("x", "y", "width", "height"))
            box = (shift[0] + x, shift[1] + y, shift[0] + x + w - 1, shift[1] + y + h - 1)
            pencil.rounded_rectangle(box, float(element.attrib.get("rx", 0)) * zoom, fill=255)
        elif element.tag == f"{NS}path":
            for polygon in flatten(element.attrib["d"]):
                pencil.polygon([(shift[0] + px * zoom, shift[1] + py * zoom) for px, py in polygon], fill=255)
        layer = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
        layer.paste(fill, (0, 0), mask)
        image.alpha_composite(layer)

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
    """The mark, then "St*arr Studio" as outlines: "St", the star, "arr", and "Studio" in the accent colour."""
    import uharfbuzz as hb
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.ttLib import TTFont

    font = TTFont(font_path)
    glyphs, order = font.getGlyphSet(), font.getGlyphOrder()
    em = font["head"].unitsPerEm
    scale = TYPE / em
    face = hb.Font(hb.Face(font_path.read_bytes()))

    def shape(text: str) -> list[tuple[str, int, int, int]]:
        """(glyph name, cluster, x offset, x advance) per glyph, kerned. Each run is shaped alone: no kerning across the star."""
        buffer = hb.Buffer()
        buffer.add_str(text)
        buffer.guess_segment_properties()
        hb.shape(face, buffer, {"kern": True, "liga": True})
        return [(order[i.codepoint], i.cluster, p.x_offset, p.x_advance) for i, p in zip(buffer.glyph_infos, buffer.glyph_positions)]

    # The mark's own edges, not its 64-unit box, set the left edge and the height.
    marks = {name: [el for el in ET.parse(SVG / name).getroot() if el.tag == f"{NS}path"] for name, *_ in LOCKUPS.values()}
    points = [point for el in next(iter(marks.values())) for polygon in flatten(el.attrib["d"]) for point in polygon]
    zoom = MARK / 64
    left = min(x for x, _ in points) * zoom
    top, bottom = min(y for _, y in points) * zoom, max(y for _, y in points) * zoom
    cap = font["OS/2"].sCapHeight * scale
    baseline = (top + bottom) / 2 + cap / 2  # the words sit level with the mark's middle
    origin = 44 + GAP  # where the canvas's 44 px mark box ends, plus the gap

    paths: dict[str, list[str]] = {"word": [], "studio": []}
    x = origin

    def set_run(text: str, studio_from: int | None = None) -> None:
        nonlocal x
        for name, cluster, offset, advance in shape(text):
            pen = SVGPathPen(glyphs, ntos=lambda n: f"{n:.2f}".rstrip("0").rstrip("."))
            glyphs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, x + offset * scale, baseline)))
            if commands := pen.getCommands():
                paths["studio" if studio_from is not None and cluster >= studio_from else "word"].append(commands)
            x += advance * scale

    set_run("St")
    star_size = STAR_SIZE * TYPE
    star_x, star_y = x + STAR_SIDE * TYPE, baseline - (STAR_LIFT + STAR_SIZE) * TYPE
    x += (STAR_SIZE + 2 * STAR_SIDE) * TYPE
    set_run("arr Studio", studio_from="arr Studio".index("Studio"))
    width, height = x - left, bottom - top
    star = f'<path fill="{{}}" transform="translate({star_x:.2f} {star_y:.2f}) scale({star_size / 64:.4f})" d="{WORD_STAR}"/>'

    for name, (mark, word, studio, star_fill) in LOCKUPS.items():
        drawn = "".join("    <path " + " ".join(f'{key}="{value}"' for key, value in el.attrib.items()) + "/>\n" for el in marks[mark])
        (SVG / name).write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{left:.2f} {top:.2f} {width:.2f} {height:.2f}" width="{width * 2:.0f}" height="{height * 2:.0f}" role="img" aria-label="Starr Studio">\n'
            f'  <g transform="scale({zoom})">\n{drawn}  </g>\n'
            f'  <path fill="{word}" d="{"".join(paths["word"])}"/>\n  {star.format(star_fill)}\n  <path fill="{studio}" d="{"".join(paths["studio"])}"/>\n</svg>\n',
            encoding="utf-8",
        )


if __name__ == "__main__":
    icons()
    if len(sys.argv) > 1:
        lockups(Path(sys.argv[1]))
