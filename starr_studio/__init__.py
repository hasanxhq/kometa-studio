"""Starr Studio: a studio for organising your Plex library, with the *arr suite, powered by an unmodified Kometa install."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("starr-studio")
except PackageNotFoundError:  # running from a source tree without installing
    __version__ = "0.0.0+unknown"
