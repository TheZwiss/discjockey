"""Discjockey: keep a lossless DJ library in sync with Spotify playlists."""
from pathlib import Path

__version__ = "1.0.0"  # the one version source (spec public-release §7); pyproject.toml repeats it, a test compares

# The source checkout. Developer runs use it (tools.check_command's `python -m discjockey`, the console Setup's alias tip, and any
# lookup of files that ship beside the source). The frozen app never does: there it is Contents/Frameworks. Never a place for user data.
REPO = Path(__file__).resolve().parents[1]
