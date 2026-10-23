import io
import json
import platform
import re
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

from packaging_helpers import PACKAGING, load

fetch_tools = load("fetch_tools")
ARM64_HEAD = b"\xcf\xfa\xed\xfe" + (0x0100000C).to_bytes(4, "little") + b"\0" * 24
X86_HEAD = b"\xcf\xfa\xed\xfe" + (0x01000007).to_bytes(4, "little") + b"\0" * 24


def zip_with(member: str, data: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(member, data)
    return buf.getvalue()


def pins_for(tmp_path, archives: dict[str, bytes], sha=None):
    pins = {name: {"version": "1", "url": f"https://example.invalid/{name}.zip",
                   "sha256": sha or fetch_tools.sha256_bytes(data), "member": name}
            for name, data in archives.items()}
    path = tmp_path / "tools.json"
    path.write_text(json.dumps(pins))
    return path


class Server:
    def __init__(self, archives: dict[str, bytes]):
        self.archives, self.calls = archives, []

    def __call__(self, url, dest):
        self.calls.append(url)
        dest.write_bytes(self.archives[url.rsplit("/", 1)[1].removesuffix(".zip")])


def test_the_pins_are_complete():
    pins = json.loads((PACKAGING / "tools.json").read_text())
    assert sorted(pins) == ["deno", "ffmpeg"]
    assert fetch_tools.programs_of(pins) == ["ffmpeg", "ffprobe", "deno"]
    for name, pin in pins.items():
        assert pin["url"].startswith("https://") and pin["version"] in pin["url"]
        assert re.fullmatch(r"[0-9a-f]{64}", pin["sha256"])
    assert pins["deno"]["member"] == "deno"


def test_ffmpeg_is_built_from_its_own_source_release_without_any_external_library():
    """Issue 19: no third-party library (libzvbi had GPL-2.0-only files) is compiled into the ffmpeg the app ships;
    only FFmpeg's own code and macOS system libraries. Autodetection is off, so nothing on the build Mac sneaks in."""
    pin = json.loads((PACKAGING / "tools.json").read_text())["ffmpeg"]
    assert pin["url"] == f"https://ffmpeg.org/releases/ffmpeg-{pin['version']}.tar.xz"
    assert pin["programs"] == ["ffmpeg", "ffprobe"]
    configure = pin["configure"]
    assert "--disable-autodetect" in configure
    assert {"--enable-gpl", "--enable-version3", "--disable-ffplay"} <= set(configure)
    enabled = {arg.removeprefix("--enable-") for arg in configure if arg.startswith("--enable-")}
    assert enabled == {"gpl", "version3", "pthreads", "zlib", "bzlib", "securetransport"}
    assert "--extra-cflags=-mmacosx-version-min=12.0" in configure  # = app_info.MIN_MACOS
    assert "--extra-ldflags=-mmacosx-version-min=12.0" in configure
    assert (PACKAGING / "build_ffmpeg.sh").is_file()


def test_packaging_is_no_python_package():
    import packaging.version  # the PyPI one, which pytest and PyInstaller need
    assert not (PACKAGING / "__init__.py").exists() and "site-packages" in packaging.version.__file__


def test_a_good_download_lands_in_bin(tmp_path):
    archives = {"ffmpeg": zip_with("ffmpeg", ARM64_HEAD)}
    out = fetch_tools.fetch_all(tmp_path / "out", tmp_path / "cache", pins_for(tmp_path, archives), Server(archives))
    assert out == [tmp_path / "out" / "bin" / "ffmpeg"]
    assert out[0].read_bytes() == ARM64_HEAD and out[0].stat().st_mode & 0o111


def test_a_hash_mismatch_fails_and_keeps_nothing(tmp_path):
    archives = {"ffmpeg": zip_with("ffmpeg", ARM64_HEAD)}
    with pytest.raises(fetch_tools.FetchError, match="SHA-256"):
        fetch_tools.fetch_all(tmp_path / "out", tmp_path / "cache", pins_for(tmp_path, archives, sha="0" * 64),
                              Server(archives))
    assert list((tmp_path / "cache").iterdir()) == [] and not (tmp_path / "out").exists()


def test_a_cached_download_is_not_fetched_again(tmp_path):
    archives = {"deno": zip_with("deno", ARM64_HEAD)}
    pins, server = pins_for(tmp_path, archives), Server(archives)
    fetch_tools.fetch_all(tmp_path / "out", tmp_path / "cache", pins, server)
    fetch_tools.fetch_all(tmp_path / "out", tmp_path / "cache", pins, server)
    assert len(server.calls) == 1


@pytest.mark.parametrize("member,data,message", [("other", ARM64_HEAD, "is not in"),
                                                  ("ffprobe", X86_HEAD, "not an arm64 macOS program")])
def test_a_wrong_archive_fails(tmp_path, member, data, message):
    archives = {"ffprobe": zip_with(member, data)}
    with pytest.raises(fetch_tools.FetchError, match=message):
        fetch_tools.fetch_all(tmp_path / "out", tmp_path / "cache", pins_for(tmp_path, archives), Server(archives))


def test_a_corrupted_cached_archive_is_downloaded_again(tmp_path):
    archives = {"deno": zip_with("deno", ARM64_HEAD)}
    pins_path, server = pins_for(tmp_path, archives), Server(archives)
    sha = json.loads(pins_path.read_text())["deno"]["sha256"]
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / f"{sha}.zip").write_bytes(zip_with("deno", X86_HEAD))  # not the pinned bytes
    out = fetch_tools.fetch_all(tmp_path / "out", tmp_path / "cache", pins_path, server)
    assert len(server.calls) == 1 and out[0].read_bytes() == ARM64_HEAD
    assert fetch_tools.sha256(tmp_path / "cache" / f"{sha}.zip") == sha


def test_a_failure_halfway_leaves_no_partial_bin(tmp_path):
    archives = {"ffmpeg": zip_with("ffmpeg", ARM64_HEAD), "ffprobe": zip_with("ffprobe", X86_HEAD)}
    with pytest.raises(fetch_tools.FetchError, match="not an arm64"):
        fetch_tools.fetch_all(tmp_path / "out", tmp_path / "cache", pins_for(tmp_path, archives), Server(archives))
    assert not (tmp_path / "out").exists()
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".")] == []  # no staging folder left


def test_a_failure_keeps_an_earlier_complete_bin_and_a_success_replaces_it(tmp_path):
    out = tmp_path / "out"
    (out / "bin").mkdir(parents=True)
    (out / "bin" / "stale").write_bytes(b"old")
    bad = {"ffmpeg": zip_with("other", ARM64_HEAD)}
    with pytest.raises(fetch_tools.FetchError):
        fetch_tools.fetch_all(out, tmp_path / "cache", pins_for(tmp_path, bad), Server(bad))
    assert (out / "bin" / "stale").exists()
    good = {"ffmpeg": zip_with("ffmpeg", ARM64_HEAD)}
    fetch_tools.fetch_all(out, tmp_path / "cache", pins_for(tmp_path, good), Server(good))
    assert sorted(p.name for p in (out / "bin").iterdir()) == ["ffmpeg"]


def tarball_pins(tmp_path, source: bytes, configure=("--enable-gpl",), sha=None):
    pins = {"ffmpeg": {"version": "1", "url": "https://example.invalid/ffmpeg.tar.xz",
                       "sha256": sha or fetch_tools.sha256_bytes(source), "programs": ["ffmpeg", "ffprobe"],
                       "configure": list(configure)}}
    path = tmp_path / "tools.json"
    path.write_text(json.dumps(pins))
    return path


class Builder:
    """Stands in for build_ffmpeg.sh: writes the programs it is told to into the out folder."""
    def __init__(self, programs=("ffmpeg", "ffprobe"), head=ARM64_HEAD):
        self.programs, self.head, self.calls = programs, head, []

    def __call__(self, source, configure, out):
        self.calls.append((source.read_bytes(), configure))
        out.mkdir(parents=True)
        for program in self.programs:
            (out / program).write_bytes(self.head + program.encode())


def source_server(source: bytes):
    calls = []

    def download(url, dest):
        calls.append(url)
        dest.write_bytes(source)
    return download, calls


def test_a_source_pin_is_built_with_its_configure_arguments_and_lands_in_bin(tmp_path):
    download, calls = source_server(b"source")
    builder = Builder()
    pins = tarball_pins(tmp_path, b"source", configure=("--enable-gpl", "--disable-doc"))
    out = fetch_tools.fetch_all(tmp_path / "out", tmp_path / "cache", pins, download, builder)
    assert out == [tmp_path / "out" / "bin" / "ffmpeg", tmp_path / "out" / "bin" / "ffprobe"]
    assert builder.calls == [(b"source", ["--enable-gpl", "--disable-doc"])]
    assert out[1].read_bytes() == ARM64_HEAD + b"ffprobe" and out[1].stat().st_mode & 0o111
    assert calls == ["https://example.invalid/ffmpeg.tar.xz"]


def test_a_cached_build_is_neither_fetched_nor_built_again(tmp_path):
    download, calls = source_server(b"source")
    builder = Builder()
    pins = tarball_pins(tmp_path, b"source")
    fetch_tools.fetch_all(tmp_path / "out", tmp_path / "cache", pins, download, builder)
    fetch_tools.fetch_all(tmp_path / "out", tmp_path / "cache", pins, download, builder)
    assert len(calls) == 1 and len(builder.calls) == 1


def test_other_configure_arguments_build_again(tmp_path):
    download, _ = source_server(b"source")
    builder = Builder()
    fetch_tools.fetch_all(tmp_path / "out", tmp_path / "cache", tarball_pins(tmp_path, b"source"), download, builder)
    fetch_tools.fetch_all(tmp_path / "out", tmp_path / "cache",
                          tarball_pins(tmp_path, b"source", configure=("--enable-gpl", "--disable-network")),
                          download, builder)
    assert [configure for _, configure in builder.calls] == [["--enable-gpl"], ["--enable-gpl", "--disable-network"]]


def test_a_source_hash_mismatch_fails_before_building(tmp_path):
    download, _ = source_server(b"tampered")
    builder = Builder()
    with pytest.raises(fetch_tools.FetchError, match="SHA-256"):
        fetch_tools.fetch_all(tmp_path / "out", tmp_path / "cache", tarball_pins(tmp_path, b"source"), download,
                              builder)
    assert builder.calls == [] and not (tmp_path / "out").exists()


@pytest.mark.parametrize("builder,message", [(Builder(programs=("ffmpeg",)), "made no ffprobe"),
                                             (Builder(head=X86_HEAD), "not an arm64 macOS program")])
def test_a_bad_build_fails_and_keeps_no_bin(tmp_path, builder, message):
    download, _ = source_server(b"source")
    with pytest.raises(fetch_tools.FetchError, match=message):
        fetch_tools.fetch_all(tmp_path / "out", tmp_path / "cache", tarball_pins(tmp_path, b"source"), download,
                              builder)
    assert not (tmp_path / "out").exists()
    # neither a staging folder nor a cached build is left: the next run builds again
    assert [p.name for p in (tmp_path / "cache").iterdir()] == [f"{fetch_tools.sha256_bytes(b'source')}.tar.xz"]


def test_a_broken_cached_build_is_built_again(tmp_path):
    download, _ = source_server(b"source")
    pins = tarball_pins(tmp_path, b"source")
    fetch_tools.fetch_all(tmp_path / "out", tmp_path / "cache", pins, download, Builder())
    built = next(p for p in (tmp_path / "cache").iterdir() if p.name.startswith("build-"))
    (built / "ffprobe").unlink()
    builder = Builder()
    out = fetch_tools.fetch_all(tmp_path / "out", tmp_path / "cache", pins, download, builder)
    assert len(builder.calls) == 1 and out[1].read_bytes() == ARM64_HEAD + b"ffprobe"


def test_a_failed_build_command_leaves_no_cached_build(tmp_path):
    download, _ = source_server(b"source")

    def failing(source, configure, out):
        out.mkdir(parents=True)
        (out / "ffmpeg").write_bytes(ARM64_HEAD)
        raise subprocess.CalledProcessError(1, ["sh", "build_ffmpeg.sh"])
    with pytest.raises(subprocess.CalledProcessError):
        fetch_tools.fetch_all(tmp_path / "out", tmp_path / "cache", tarball_pins(tmp_path, b"source"), download,
                              failing)
    assert sorted(p.name for p in (tmp_path / "cache").iterdir()) == [f"{fetch_tools.sha256_bytes(b'source')}.tar.xz"]


def test_the_build_key_follows_the_build_script(tmp_path):
    pin = {"sha256": "a" * 64, "configure": ["--enable-gpl"]}
    script = tmp_path / "build.sh"
    script.write_text("one")
    first = fetch_tools.build_key(pin, script)
    script.write_text("two")
    assert fetch_tools.build_key(pin, script) != first


def test_a_fresh_build_replaces_the_cached_build_but_keeps_the_cached_download(tmp_path):
    """The release job signs what it ships, and a cached build can't be checked against a hash: it builds its own."""
    download, calls = source_server(b"source")
    pins = tarball_pins(tmp_path, b"source")
    fetch_tools.fetch_all(tmp_path / "out", tmp_path / "cache", pins, download, Builder())
    builder = Builder()
    out = fetch_tools.fetch_all(tmp_path / "out", tmp_path / "cache", pins, download, builder, fresh_build=True)
    assert len(builder.calls) == 1 and len(calls) == 1  # built again, not downloaded again
    assert out[0].read_bytes() == ARM64_HEAD + b"ffmpeg"
    fetch_tools.fetch_all(tmp_path / "out", tmp_path / "cache", pins, download, builder)
    assert len(builder.calls) == 1  # the new build is the cached one again


def test_a_failed_fresh_build_does_not_fall_back_to_the_old_cached_build(tmp_path):
    download, _ = source_server(b"source")
    pins = tarball_pins(tmp_path, b"source")
    fetch_tools.fetch_all(tmp_path / "out", tmp_path / "cache", pins, download, Builder())
    with pytest.raises(fetch_tools.FetchError, match="made no ffprobe"):
        fetch_tools.fetch_all(tmp_path / "out", tmp_path / "cache", pins, download, Builder(programs=("ffmpeg",)),
                              fresh_build=True)
    assert not any(p.name.startswith("build-") for p in (tmp_path / "cache").iterdir())


def test_the_command_line_has_a_fresh_build_flag(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(fetch_tools, "fetch_all", lambda out, cache, **kw: seen.append(kw["fresh_build"]) or [])
    assert fetch_tools.main(["--out", str(tmp_path / "o")]) == 0
    assert fetch_tools.main(["--out", str(tmp_path / "o"), "--fresh-build"]) == 0
    assert seen == [False, True]


needs_apple_silicon = pytest.mark.skipif(not (platform.system() == "Darwin" and platform.machine() == "arm64"),
                                         reason="build_ffmpeg.sh builds for an Apple Silicon Mac")


def stub_ffmpeg_source(tmp_path) -> Path:
    """A stand-in for FFmpeg's source release: a configure that does nothing and a Makefile that compiles thin
    arm64 programs."""
    source = tmp_path / "ffmpeg-0"
    source.mkdir()
    (source / "configure").write_text("#!/bin/sh\nexit 0\n")
    (source / "configure").chmod(0o755)
    (source / "Makefile").write_text("ffmpeg ffprobe:\n\techo 'int main(void){return 0;}' | clang -x c - -arch arm64 -o $@\n")
    tarball = tmp_path / "ffmpeg-0.tar.xz"
    with tarfile.open(tarball, "w:xz") as tar:
        tar.add(source, arcname="ffmpeg-0")
    return tarball


@needs_apple_silicon
def test_the_real_build_script_delivers_into_a_relative_cache(tmp_path, monkeypatch):
    """C1: both workflows call `fetch_tools.py --out dist/tools --cache dist/cache`, relative paths, and the script
    cds into the source before it writes its output."""
    tarball = stub_ffmpeg_source(tmp_path)
    pins = tarball_pins(tmp_path, tarball.read_bytes(), configure=("--prefix=/nowhere",))
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    out = fetch_tools.fetch_all(Path("dist/tools"), Path("dist/cache"), pins,
                                lambda url, dest: dest.write_bytes(tarball.read_bytes()))
    assert [p.name for p in out] == ["ffmpeg", "ffprobe"]
    assert all(p.is_file() and p.stat().st_mode & 0o111 for p in out)
    assert (work / "dist" / "tools" / "bin" / "ffmpeg").is_file()


@needs_apple_silicon
def test_the_build_script_itself_takes_relative_paths(tmp_path):
    tarball = stub_ffmpeg_source(tmp_path)
    subprocess.run(["sh", str(PACKAGING / "build_ffmpeg.sh"), tarball.name, "made/here", "--prefix=/nowhere"],
                   cwd=tmp_path, check=True)
    assert sorted(p.name for p in (tmp_path / "made" / "here").iterdir()) == ["ffmpeg", "ffprobe"]
