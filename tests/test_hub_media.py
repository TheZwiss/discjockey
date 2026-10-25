import http.client
import urllib.parse

import pytest
from audio_helpers import needs_ffmpeg, write_aiff

from discjockey import audio
from discjockey.hub import media
from discjockey.hub.media import MediaServer
from discjockey.library import Paths

NAME = "Library/Hard_Bounce/BΞNZ0 - Bass Is Coming.aiff"
AUDIO = bytes(range(256)) * 40


@pytest.fixture
def server(tmp_path):
    paths = Paths(tmp_path, support=tmp_path / ".support")
    for rel, data in [(NAME, AUDIO), ("Superseded/A/x (lossy).aiff", b"old"), ("Upgrades ready/A/x.aiff", b"new"),
                      (".support/cache/previews/youtube_abc.aiff", b"preview"),
                      (".support/cache/covers/t1.jpg", b"\xff\xd8\xffcover"),
                      (".discjockey/state.json", b"{}")]:
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
    (tmp_path / "secret.txt").write_text("secret")
    s = MediaServer(paths)
    s.start()
    yield s
    s.stop()


def get(server, path, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.request("GET", path, headers=headers or {})
    r = conn.getresponse()
    body = r.read()
    conn.close()
    return r.status, dict(r.getheaders()), body


def test_url_is_quoted_and_carries_size_and_mtime(server):
    url = server.url(NAME)
    f = server.paths.root / NAME
    parsed = urllib.parse.urlsplit(url)
    assert parsed.hostname == "127.0.0.1" and parsed.port == server.port
    assert " " not in url and parsed.query == f"v={f.stat().st_size}-{f.stat().st_mtime_ns}"
    assert urllib.parse.unquote(parsed.path) == f"/{server.token}/{NAME}"


def test_plays_a_library_file(server):
    status, headers, body = get(server, urllib.parse.urlsplit(server.url(NAME)).path)
    assert status == 200 and body == AUDIO and headers["Content-Type"].startswith("audio/")


def test_answers_range_requests(server):
    path = urllib.parse.urlsplit(server.url(NAME)).path
    status, headers, body = get(server, path, {"Range": "bytes=0-1"})  # WebKit's first probe
    assert status == 206 and body == AUDIO[:2] and headers["Content-Range"] == f"bytes 0-1/{len(AUDIO)}"
    status, headers, body = get(server, path, {"Range": "bytes=1000-"})
    assert status == 206 and body == AUDIO[1000:]


@pytest.mark.parametrize("rel", ["Superseded/A/x (lossy).aiff", "Upgrades ready/A/x.aiff",
                                 "cache/previews/youtube_abc.aiff", "cache/covers/t1.jpg"])
def test_serves_the_other_allowed_folders(server, rel):
    assert get(server, urllib.parse.urlsplit(server.url(rel)).path)[0] == 200


def test_wrong_token_is_refused(server):
    path = urllib.parse.urlsplit(server.url(NAME)).path.replace(server.token, "x" * len(server.token))
    assert get(server, path)[0] == 403


@pytest.mark.parametrize("raw", [
    ".discjockey/state.json",
    "Library/../secret.txt",
    "Library/%2e%2e/secret.txt",
    "Library/%2E%2E/.discjockey/state.json",
    "secret.txt",
    "%2Fetc%2Fpasswd",
    "Library",
    ".support/cache/covers/t1.jpg",
    "cache/../secret.txt",
    "cache/spectrum/x.json",
])
def test_paths_outside_the_folders_are_refused(server, raw):
    status, _, body = get(server, f"/{server.token}/{raw}")
    assert status in (403, 404) and body not in (b"secret", b"{}")


def test_url_refuses_paths_outside_the_folders(server):
    assert server.url(".discjockey/state.json") is None
    assert server.url("Library/../secret.txt") is None
    assert server.url("Library/Hard_Bounce/missing.aiff") is None


def test_a_link_out_of_the_folders_is_refused(server, tmp_path):
    (tmp_path / "Library" / "link.aiff").symlink_to(tmp_path / "secret.txt")
    assert server.url("Library/link.aiff") is None
    assert get(server, f"/{server.token}/Library/link.aiff")[0] == 403


def test_only_local(server):
    assert server.host == "127.0.0.1"


# --- covers from the file's own tags, cached in the support folder's cache/covers/ ---

JPEG = b"\xff\xd8\xff\xe0" + b"jpeg data" * 10


@needs_ffmpeg
def test_cover_from_the_embedded_tag_is_cached(tmp_path):
    import numpy as np
    paths = Paths(tmp_path, support=tmp_path / ".support")
    rel = "Library/A/Artist - Song.aiff"
    (tmp_path / rel).parent.mkdir(parents=True)
    write_aiff(tmp_path / rel, np.zeros(44100, dtype=np.float32))
    audio.write_tags(tmp_path / rel, title="Song", artists=("Artist",), album="", isrc=None, label=None, cover=JPEG,
                     comment="x")
    got = media.cover_file(paths, rel)
    assert got.startswith("cache/covers/") and got.endswith(".jpg")
    assert (paths.cache / got.removeprefix("cache/")).read_bytes() == JPEG
    calls = []
    real = media._embedded_cover
    media._embedded_cover = lambda p: calls.append(p) or real(p)
    try:
        assert media.cover_file(paths, rel) == got and calls == []  # from the cache
    finally:
        media._embedded_cover = real


def test_no_cover_is_remembered_too(tmp_path, monkeypatch):
    paths = Paths(tmp_path, support=tmp_path / ".support")
    rel = "Library/A/x.wav"
    (tmp_path / rel).parent.mkdir(parents=True)
    (tmp_path / rel).write_bytes(b"not really audio")
    calls = []
    monkeypatch.setattr(media, "_embedded_cover", lambda p: calls.append(p) or None)
    assert media.cover_file(paths, rel) is None and media.cover_file(paths, rel) is None
    assert len(calls) == 1
    assert media.cover_file(paths, "Library/A/missing.aiff") is None


def test_nothing_is_served_before_a_library_is_bound(tmp_path):
    s = MediaServer()
    assert s.url(NAME) is None and s.allowed("cache/covers/t1.jpg") is None
    s.bind(Paths(tmp_path, support=tmp_path / ".support"))
    (tmp_path / NAME).parent.mkdir(parents=True)
    (tmp_path / NAME).write_bytes(AUDIO)
    assert s.allowed(NAME) == (tmp_path / NAME).resolve()



def test_a_file_address_is_served_through_the_hubs_resolver(tmp_path):
    outside = tmp_path / "Example Drive" / "Music"
    outside.mkdir(parents=True)
    (outside / "Mine.aiff").write_bytes(AUDIO)
    known = {7: outside / "Mine.aiff"}
    s = MediaServer(Paths(tmp_path / "music", support=tmp_path / ".support"), files=known.get)
    s.start()
    try:
        url = s.url(media.file_address(7))
        assert url is not None and urllib.parse.urlsplit(url).path == f"/{s.token}/file/7"
        status, headers, body = get(s, urllib.parse.urlsplit(url).path)
        assert status == 200 and body == AUDIO and headers["Content-Type"].startswith("audio/")
        for refused in ("file/8", "file/x", "file/", "file/7/extra", "file/-7", "file/7.0", "File/7"):
            assert s.url(refused) is None, refused
        assert get(s, f"/{s.token}/file/8")[0] == 403
        assert get(s, "/wrong/file/7")[0] == 403
        s.files = None  # nothing resolves without a resolver
        assert s.url("file/7") is None

        def broken(n):
            raise OSError("records unreadable")

        s.files = broken
        assert s.url("file/7") is None
    finally:
        s.stop()


def test_file_inside_keeps_a_file_within_its_folder(tmp_path):
    root = tmp_path / "Music"
    root.mkdir()
    (root / "a.aiff").write_bytes(b"a")
    (tmp_path / "secret.aiff").write_bytes(b"s")
    (root / "escape.aiff").symlink_to(tmp_path / "secret.aiff")
    (root / "inside.aiff").symlink_to(root / "a.aiff")
    (root / "sub").mkdir()
    assert media.file_inside(root, "a.aiff") == (root / "a.aiff").resolve()
    assert media.file_inside(root, "inside.aiff") == (root / "a.aiff").resolve()
    assert media.file_inside(root, "escape.aiff") is None
    assert media.file_inside(root, "../secret.aiff") is None
    assert media.file_inside(root, "sub") is None and media.file_inside(root, "missing.aiff") is None
