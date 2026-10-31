"""Read and validate playlists.txt."""
from __future__ import annotations

import unicodedata
from pathlib import Path

from . import sources
from .models import PlaylistLine, token
from .names import fold


class ConfigError(Exception):
    """kind: not_set_up (no playlists.txt or no active line yet) | config_invalid (a line to fix)."""

    def __init__(self, message: str, kind: str = "config_invalid"):
        super().__init__(message)
        self.kind = kind


def _check_folder(folder: str, where: str) -> None:
    if not folder:
        raise ConfigError(f"{where}: the folder name in front of = is empty.")
    if fold(folder) == "not_lossless":
        raise ConfigError(f"{where}: 'not_lossless' is reserved, pick another folder name.")
    if any(c in folder for c in "/\\:"):
        raise ConfigError(f"{where}: folder names cannot contain / \\ or :")
    if folder.startswith("."):
        raise ConfigError(f"{where}: folder names cannot start with a dot.")
    if len(folder) > 100:
        raise ConfigError(f"{where}: the folder name is longer than 100 characters.")


def parse_playlists(text: str) -> list[PlaylistLine]:
    result: list[PlaylistLine] = []
    folders: dict[str, int] = {}
    ids: dict[str, int] = {}
    for no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        where = f"playlists.txt line {no}"
        if "=" not in line:
            raise ConfigError(f"{where}: expected 'Folder = playlist link', found: {line}")
        folder, ref = (part.strip() for part in line.split("=", 1))
        folder = unicodedata.normalize("NFC", folder)
        _check_folder(folder, where)
        if not ref:
            raise ConfigError(
                f"{where}: the link after = is empty. Paste the playlist link, "
                "or put # in front of the line to switch it off."
            )
        found = sources.recognise(ref)
        if found is None:
            raise ConfigError(f"{where}: this is not a playlist link Discjockey can read ({sources.service_list()}): "
                              f"{ref}")
        service, pid = found
        if fold(folder) in folders:
            raise ConfigError(f"{where}: the folder {folder} is already used on line {folders[fold(folder)]}.")
        if token(service, pid) in ids:
            raise ConfigError(f"{where}: this playlist is already listed on line {ids[token(service, pid)]}.")
        folders[fold(folder)] = no
        ids[token(service, pid)] = no
        result.append(PlaylistLine(folder, pid, no, service))
    if not result:
        raise ConfigError(
            "playlists.txt has no active playlists. Add a line like: "
            "Hard_Bounce = https://open.spotify.com/playlist/...", "not_set_up"
        )
    return result


def load_playlists(path: Path) -> list[PlaylistLine]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise ConfigError(f"{path} does not exist. Run: discjockey setup", "not_set_up") from None
    return parse_playlists(text)
