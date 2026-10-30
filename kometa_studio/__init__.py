"""Kometa Studio: an arr-style web GUI that drives an unmodified Kometa install."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("kometa-studio")
except PackageNotFoundError:  # running from a source tree without installing
    __version__ = "0.0.0+unknown"
