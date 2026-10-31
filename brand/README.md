# Streak K

The Kometa Studio logo: a K whose upper arm is a comet. Design source: the [logo canvas](https://claude.ai/artifact/FZ6XVPHYfRpmPpSFVjV8Ez) (private until shared).

## What's here

| Path | Use |
| ---- | ---- |
| `svg/mark-on-dark.svg` | Mark for dark backgrounds, such as the app and GitHub dark mode |
| `svg/mark-on-light.svg` | Mark for light backgrounds, such as docs and GitHub light mode |
| `svg/mark-mono.svg` | One colour, inherits `currentColor` |
| `svg/lockup-on-dark.svg`, `svg/lockup-on-light.svg` | Mark and name, with the words as outlines so they need no font |
| `svg/favicon.svg`, `svg/icon-*.svg` | Masters for the favicon and app icons |
| `build_icons.py` | Rebuilds the files below from the SVGs |

The app uses `frontend/public/` (favicons, app icons, web manifest) and `frontend/src/components/StreakMark.tsx`, which is the mark coloured by the app's Tailwind tokens.

## Colours

| Use | Value | Token |
| --- | ----- | ----- |
| Comet on dark, favicon tile | `#f2b544` | `--color-accent` |
| K on dark | `#ecedee` | `--color-text` |
| Favicon K, mark on light | `#1a1406` | `--color-on-accent` |
| App icon background | `#0f1114` | `--color-bg` |
| Comet on light | `#b87a0a` | none, only on light backgrounds |
| "Studio" on light | `#8a5a00` | none, only on light backgrounds |

Plain amber is too faint on white, so on light backgrounds always use the `on-light` files.

## Usage

- **Smallest size:** 20px tall for the mark. Below that, use the favicon, which is redrawn on a 16-pixel grid so its edges land on whole pixels.
- **Clear space:** keep at least the width of the K's stem (about 1/6 of the mark's height) free on every side.
- **Lockup:** the mark followed by "Kometa Studio" in Space Grotesk 600, with "Studio" in the accent colour. In the app, it's the mark plus live text.
- **Don't** put the comet on an amber background in two colours (it disappears), add flames, or place the K inside a circle. Those belong to the upstream Kometa logo.

## Rebuilding

Edit the SVGs, then run this from this folder:

```bash
uv run --no-project --with pillow --with fonttools python build_icons.py
```

To redraw the lockups too, add `--with uharfbuzz` and the path to `SpaceGrotesk-SemiBold.ttf`. Space Grotesk is under the SIL Open Font License, from [Google Fonts](https://fonts.google.com/specimen/Space+Grotesk). It isn't kept in this repository.

The icons' `<g>` elements repeat their transform in `data-place` (x, y, scale), which is what `build_icons.py` reads.
