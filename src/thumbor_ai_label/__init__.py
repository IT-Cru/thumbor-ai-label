"""Thumbor plugin: AI provenance detection and visible AI labelling."""

from importlib.metadata import PackageNotFoundError, version as _version

try:
    #: Single source of truth is the distribution metadata built from pyproject.toml,
    #: so the version cannot drift between the two the way a hard-coded literal here
    #: would.
    __version__ = _version("thumbor-ai-label")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0.dev0"

__all__ = ["__version__"]
