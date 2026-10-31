"""Splits the title of a SoundCloud upload or a YouTube video into artists and title (stage 6, I2). Pure.

Both new playlist services give one free-text title ("PREMIERE: Artist feat. Other - Title (Example Remix) [FREE DL]")
plus the uploader's name; every source applies `split_title` when it parses an entry, so linking, the Qobuz search
and the file names `Artist - Title` all see clean names. Rules, in order: clean the text, drop leading tags, drop tag
brackets, cut a pipe tail, split at the first spaced dash, and fall back to the known artist or the uploader.
A remix, edit, mix, bootleg, VIP, version or feat. bracket is part of the song and stays.
"""
from __future__ import annotations

import re
import unicodedata

from .matching import normalize

# Whole-bracket tags that say nothing about the song (rule 3), compared lowercase with spaces collapsed.
_TAGS = frozenset({
    "free dl", "free download", "free", "premiere", "out now", "official video", "official audio",
    "official music video", "official visualizer", "visualizer", "lyrics", "lyric video", "audio", "hq", "hd", "4k",
})

_SPACES = re.compile(r"\s+")
_BRACKET = re.compile(r"[\(\[]([^\(\)\[\]]*)[\)\]]")
_DASH = re.compile(r"\s[-–—]\s")  # spaced only: "Jay-Z" and "AC-DC" keep their dash
_PIPE = re.compile(r"\s\|\s")
_LEADING_TAG = re.compile(
    r"^(?:\[\s*(?:premiere|free dl)\s*\]|\(\s*premiere\s*\)|premiere\s*[:|]|premiere\s+[-–—]|free dl\s*:)\s*", re.I)
_FEAT_WORD = r"(?:feat|ft|featuring)\b\.?"
_FEAT_BRACKET = re.compile(rf"[\(\[]\s*{_FEAT_WORD}\s*([^\(\)\[\]]*)[\)\]]", re.I)  # "(feat. X)"
_FEAT_SPLIT = re.compile(rf"(?:^|\s+)\b{_FEAT_WORD}\s+", re.I)  # "Artist feat. X"
_FEAT_IN_TITLE = re.compile(rf"\s+\b{_FEAT_WORD}\s+([^\(\)\[\]]+?)(?=\s[-–—]\s|\s*[\(\[]|\s*$)", re.I)
_NAME_SPLIT = re.compile(r",\s*|\s+x\s+")  # a lowercase x only: "Lil Nas X" is one artist
_UPLOADER_TAIL = re.compile(r"(?:\s*-\s*Topic|\s*VEVO)\s*$", re.I)
_MIX_ONLY = re.compile(r"^(?:extended|original|radio|club|dub|vip)?\s*(?:mix|edit|version)$", re.I)  # "Extended Mix"
_DANGLING_DASH = re.compile(r"\s+[-–—]\s*$")

_STRIPPED_CATEGORIES = {"So", "Sk"}  # symbols and modifiers: emoji, pictographs, skin tones
_STRIPPED_CHARS = {
    **{c: None for c in range(0xFE00, 0xFE10)},      # variation selectors
    **{c: None for c in range(0xE0100, 0xE01F0)},    # variation selectors supplement
    **{c: None for c in range(0xE0000, 0xE0080)},    # tag characters (flag sequences)
    0x200D: None, 0x20E3: None,                      # zero width joiner, keycap
    0x2122: None, 0x2120: None,                      # TM and SM would turn into letters under NFKC
    0x00B4: "'", 0x0060: "'",                        # acute accent and grave as an apostrophe: "Don´t Stop"
}


def clean_uploader(name: str) -> str:
    """An uploader's name as an artist: without a trailing ` - Topic` (YouTube's auto-generated channels) or `VEVO`."""
    stripped = name.strip()
    cleaned = _UPLOADER_TAIL.sub("", stripped).strip()
    return cleaned or stripped


def _clean(text: str) -> str:
    """Rule 1: NFKC, no emoji or pictographs, single spaces. Letters, digits and punctuation of any script stay."""
    text = unicodedata.normalize("NFKC", text.translate(_STRIPPED_CHARS))
    text = "".join(c for c in text if unicodedata.category(c) not in _STRIPPED_CATEGORIES)
    return _SPACES.sub(" ", text).strip()


def _drop_tag_brackets(text: str, uploader: str) -> str:
    """Rule 3: whole brackets that are a pure tag, or the uploader's own name, go; every other bracket stays."""
    label = normalize(uploader)

    def repl(m: re.Match) -> str:
        inner = _SPACES.sub(" ", m.group(1)).strip().lower()
        return " " if inner in _TAGS or (label and inner and normalize(inner) == label) else m.group(0)

    return _SPACES.sub(" ", _BRACKET.sub(repl, text)).strip()


def _names(text: str) -> list[str]:
    """Rule 7: the artists inside one artist part. Splits at feat./ft./featuring (also in brackets), `, ` and a
    lowercase ` x `; `&`, `and` and `vs` stay inside one name ("Chase & Status" is one band)."""
    text = _FEAT_BRACKET.sub(lambda m: f" feat. {m.group(1)}", text)
    names: list[str] = []
    for part in _FEAT_SPLIT.split(text):
        for name in _NAME_SPLIT.split(part):
            name = name.strip(" ,")
            if name and name.lower() not in (n.lower() for n in names):
                names.append(name)
    return names


def _move_feat(title: str) -> tuple[str, list[str]]:
    """Rule 7: a `feat.` part inside the title ("Title (feat. X)", "Title feat. X") leaves the title for the artists."""
    moved: list[str] = []

    def take(m: re.Match) -> str:
        moved.extend(_names(m.group(1)))
        return " "

    title = _FEAT_BRACKET.sub(take, title)
    title = _FEAT_IN_TITLE.sub(take, title)
    return _SPACES.sub(" ", title).strip(), moved


def _contains(needle: str, haystack: str) -> bool:
    return bool(needle) and f" {needle} " in f" {haystack} "


def split_title(title: str, uploader: str, artist: str | None = None) -> tuple[tuple[str, ...], str]:
    """(artists, title) of an upload. `artist` is a known artist (SoundCloud's `publisher_metadata.artist`); `uploader`
    the SoundCloud user's name or the YouTube channel. Never returns an empty title."""
    original = title.strip()
    text = _clean(title)
    fallback_artist = (artist or "").strip() or clean_uploader(uploader)
    if not text:  # nothing but pictographs: the title stays as it was
        return tuple(_names(fallback_artist)), original

    while True:  # rule 2: leading tags, also several in a row
        stripped = _LEADING_TAG.sub("", text)
        if stripped == text:
            break
        text = stripped
    text = _drop_tag_brackets(text, uploader)  # rule 3
    pipe = _PIPE.search(text)  # rule 4
    if pipe and text[:pipe.start()].strip():
        text = text[:pipe.start()].strip()
    text = text.strip()
    if not text:  # the title was only tags
        text = _clean(title)

    known = normalize(artist) if artist else ""
    label = normalize(clean_uploader(uploader))
    left = right = ""
    m = _DASH.search(text)  # rule 5
    if m:
        left, right = text[:m.start()].strip(), text[m.end():].strip()
        if label and _DASH.search(right) and normalize(left) == label:  # "Example Records - Artist - Title"
            m2 = _DASH.search(right)
            left, right = right[:m2.start()].strip(), right[m2.end():].strip()
        if not left or not right:
            m = None
        elif known:
            left_norm = normalize(left)
            if not (_contains(known, left_norm) or _contains(left_norm, known)):
                m = None  # the known artist rules: this dash belongs to the title ("Title - Extended Mix")
        elif _MIX_ONLY.match(right):
            m = None  # "Title - Extended Mix": a mix name is no title, so the dash belongs to the title
    if m:
        artists, song = _names(left), right
    else:  # rule 6
        artists, song = _names(fallback_artist), text
    song, moved = _move_feat(song)
    song = _DANGLING_DASH.sub("", song)  # "Title - feat. Other" leaves a dash behind
    for name in moved:
        if name.lower() not in (a.lower() for a in artists):
            artists.append(name)
    return tuple(artists), song or text
