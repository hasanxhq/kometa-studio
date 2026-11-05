# Starred poster

The Starr Studio logo: three posters fanned like a hand of cards, the front one carrying an asterisk. The name is styled **St\*arr Studio**: the asterisk is a star and the wildcard in "\*arr apps". Design source: the [logo canvas](https://claude.ai/artifact/FZ6XVPHYfRpmPpSFVjV8Ez), section "St\*arr Studio", direction C (private until shared).

The styling is only for the logo and wordmark. Everywhere else, including tab titles, docs, code and screen readers, the name is written plainly: Starr Studio.

## What's here

| Path | Use |
| ---- | ---- |
| `svg/mark-on-dark.svg` | Mark for dark backgrounds, such as the app and GitHub dark mode |
| `svg/mark-on-light.svg` | Mark for light backgrounds, such as docs and GitHub light mode |
| `svg/mark-mono.svg` | One colour, inherits `currentColor`; the star is dark grey (`#3d3d3d`), drawn over the front card |
| `svg/lockup-on-dark.svg`, `svg/lockup-on-light.svg` | Mark and "St\*arr Studio", with the words as outlines so they need no font |
| `svg/favicon.svg`, `svg/icon-*.svg` | Masters for the favicon and app icons |
| `draw_mark.py` | Draws the marks, icons and favicon from their geometry |
| `build_icons.py` | Builds the lockups and the files in `frontend/public/` from the SVGs |

The app uses `frontend/public/` (favicons, app icons, web manifest) and `frontend/src/components/Logo.tsx`: `PosterMark` is the mark coloured by the app's Tailwind tokens, and `Wordmark` is "St\*arr Studio" in live text with the star drawn in.

## Colours

| Use | Value | Token |
| --- | ----- | ----- |
| Posters on dark, the star in the words | `#f2b544` | `--color-accent` |
| Star on the front poster | `#1a1406` | `--color-on-accent` |
| Words on dark | `#ecedee` | `--color-text` |
| App icon background | `#0f1114` | `--color-bg` |
| Favicon tile | `#14171b` | `--color-sidebar` |
| Posters on light, the star in the words on light | `#b87a0a` | none, only on light backgrounds |
| "Studio" on light | `#8a5a00` | none, only on light backgrounds |

The back posters are the poster colour at 30% (left) and 55% (right) opacity. Plain amber is too faint on white, so on light backgrounds always use the `on-light` files.

## Usage

- **Smallest size:** 20px tall for the mark. Below that, use the favicon, which is redrawn on a 16-pixel grid with two posters.
- **Clear space:** keep at least the width of one star arm's length (about 1/8 of the mark's height) free on every side.
- **Wordmark:** "St\*arr Studio" in Space Grotesk 600, "Studio" in the accent colour. The star is 0.46 em tall, its foot 0.26 em above the baseline (raised, like an asterisk), with 0.03 em on each side, and it uses the six-armed star from `WORD_STAR`, never a typed `*`.
- **Lockup:** the mark followed by the wordmark.
- **Don't** fan more than three posters, recolour the star on the front poster, or tilt the front poster. Don't type the stylised name in running text.

## Rebuilding

To change the mark, edit the geometry in `draw_mark.py` and run it from this folder. It rewrites the SVGs and prints the paths to copy into `build_icons.py` (`WORD_STAR`) and `Logo.tsx`. Then rebuild the rest:

```bash
uv run --no-project --with pillow --with fonttools python build_icons.py
```

To redraw the lockups too, add `--with uharfbuzz` and the path to `SpaceGrotesk-SemiBold.ttf`. Space Grotesk is under the SIL Open Font License, from [Google Fonts](https://fonts.google.com/specimen/Space+Grotesk). It isn't kept in this repository. Google Fonts ships it as a variable font; a weight-600 instance (`fontTools.varLib.instancer`, `{"wght": 600}`) is the face the lockups were drawn with.

The icons' `<g>` elements repeat their transform in `data-place` (x, y, scale), which is what `build_icons.py` reads. Its rasteriser draws filled `rect` and `path` elements with `fill` and `opacity`, nothing else.
