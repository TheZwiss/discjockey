import importlib.metadata as md
import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from packaging_helpers import PACKAGING, load

import discjockey

collect_licenses = load("collect_licenses")


def make_dist(site: Path, name: str, version: str, files: dict[str, str], license_meta: str | None = None) -> None:
    info = site / f"{name.replace('-', '_')}-{version}.dist-info"
    info.mkdir(parents=True)
    meta = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
    (info / "METADATA").write_text(meta + (f"License: {license_meta}\n" if license_meta else ""))
    record = [f"{info.name}/METADATA,,"]
    for rel, text in files.items():
        (info / rel).parent.mkdir(parents=True, exist_ok=True)
        (info / rel).write_text(text)
        record.append(f"{info.name}/{rel},,")
    (info / "RECORD").write_text("\n".join(record) + "\n")


def run(tmp_path, dists_setup, hand_files: dict[str, str] | None = None) -> tuple[Path, list[str]]:
    site, hand, out = tmp_path / "site", tmp_path / "hand", tmp_path / "out"
    site.mkdir()
    hand.mkdir()
    (hand / "ffmpeg.txt").write_text("FFmpeg notice")
    for name, text in (hand_files or {}).items():
        (hand / name).write_text(text)
    python_licence = tmp_path / "LICENSE.txt"
    python_licence.write_text("PSF")
    dists_setup(site)
    problems = collect_licenses.collect(out, md.distributions(path=[str(site)]), hand, python_licence)
    return out, problems


def test_licence_files_and_hand_kept_texts_are_collected(tmp_path):
    out, problems = run(tmp_path, lambda site: make_dist(site, "mutagen", "1.47.0",
                                                          {"licenses/COPYING": "GPL-2.0-or-later text"}))
    assert problems == []
    assert (out / "python" / "mutagen-1.47.0" / "COPYING").read_text() == "GPL-2.0-or-later text"
    assert (out / "ffmpeg.txt").read_text() == "FFmpeg notice"
    assert list((out / "python").glob("Python-*/LICENSE.txt"))
    assert "mutagen 1.47.0" in (out / "INDEX.txt").read_text()


def test_metadata_only_licences_are_written_down(tmp_path):
    out, problems = run(tmp_path, lambda site: make_dist(site, "bottle", "0.13.4", {}, license_meta="MIT"))
    assert problems == []
    assert (out / "python" / "bottle-0.13.4" / "LICENSE-METADATA.txt").read_text() == "bottle 0.13.4: MIT\n"


def install(site: Path, name: str, version: str, files: list[str], licence: str = "MIT") -> None:
    """A distribution with files outside its .dist-info (code, data, binaries), all in its RECORD."""
    make_dist(site, name, version, {}, license_meta=licence)
    info = site / f"{name.replace('-', '_')}-{version}.dist-info"
    for rel in files:
        (site / rel).parent.mkdir(parents=True, exist_ok=True)
        (site / rel).write_text(rel)
    with (info / "RECORD").open("a") as record:
        record.writelines(f"{rel},,\n" for rel in files)


def venv(site: Path) -> None:
    install(site, "mutagen", "1.47.0", ["mutagen/__init__.py", "mutagen/flac.py"])
    install(site, "certifi", "2026.1.1", ["certifi/cacert.pem"])  # what the app takes from it is data only
    install(site, "pyobjc-core", "12.2.2", ["objc/_objc.cpython-312-darwin.so"])  # a binary
    install(site, "pytest", "9.1.1", ["pytest/__init__.py", "_pytest/main.py"])  # in the venv, not in the app
    install(site, "pyobjc-framework-quartz", "12.2.2", ["Quartz/__init__.py"])
    make_dist(site, "metadata-only", "1.0", {}, license_meta="MIT")


def test_only_distributions_with_files_in_the_bundle_are_listed(tmp_path):
    site = tmp_path / "site"
    venv(site)
    sources = [site / "mutagen" / "flac.py", site / "certifi" / "cacert.pem", site / "objc" / "_objc.cpython-312-darwin.so",
               site / "metadata_only-1.0.dist-info" / "METADATA",  # copied metadata alone ships no code
               tmp_path / "python" / "lib" / "json" / "__init__.py"]  # the standard library: Python's licence
    names = [d.metadata["Name"] for d in collect_licenses.bundled(md.distributions(path=[str(site)]), sources)]
    assert names == ["certifi", "mutagen", "pyobjc-core"]


def test_the_cli_lists_what_the_bundled_file_names(tmp_path):
    site, out, listing = tmp_path / "site", tmp_path / "out", tmp_path / "bundled-sources.txt"
    venv(site)
    listing.write_text(f"{site / 'mutagen' / '__init__.py'}\n{site / 'certifi' / 'cacert.pem'}\n\n")
    code = collect_licenses.main(["--out", str(out), "--bundled", str(listing)],
                                 distributions=lambda: md.distributions(path=[str(site)]))
    index = (out / "INDEX.txt").read_text()
    assert code == 0 and "mutagen 1.47.0" in index and "certifi 2026.1.1" in index
    assert "pytest" not in index and "quartz" not in index and "pyobjc" not in index


def test_toc_sources_takes_the_files_pyinstaller_collected():
    pure = [("mutagen.flac", "/v/site/mutagen/flac.py", "PYMODULE"), ("pkg", "-", "PYMODULE"),
            ("frozen", None, "PYMODULE")]
    binaries = [("objc/_objc.so", "/v/site/objc/_objc.so", "EXTENSION")]
    datas = [("certifi/cacert.pem", "/v/site/certifi/cacert.pem", "DATA"), ("x", "relative/file", "DATA")]
    assert collect_licenses.toc_sources(pure, binaries, datas) == [
        Path("/v/site/mutagen/flac.py"), Path("/v/site/objc/_objc.so"), Path("/v/site/certifi/cacert.pem")]


def test_a_distribution_without_any_licence_fails(tmp_path):
    _, problems = run(tmp_path, lambda site: make_dist(site, "mystery", "1.0", {}))
    assert problems == ["mystery 1.0: no licence file and no licence metadata"]


REPO = PACKAGING.parent
PINS = json.loads((PACKAGING / "tools.json").read_text(encoding="utf-8"))


def ffmpeg_notice() -> tuple[str, str]:
    """(the whole notice, its configuration line)."""
    text = (PACKAGING / "licenses" / "ffmpeg.txt").read_text(encoding="utf-8")
    configuration = next(line for line in text.splitlines() if line.startswith("configuration:"))
    return text, configuration


def test_the_hand_kept_folder_has_the_texts():
    names = sorted(p.name for p in (PACKAGING / "licenses").iterdir())
    assert names == ["GPL-3.0.txt", "deno.txt", "ffmpeg.txt", "svelte.txt", "vite.txt"]


def test_the_ffmpeg_notice_names_the_pinned_source_and_how_it_is_built():
    pin = PINS["ffmpeg"]
    text, _ = ffmpeg_notice()
    assert text.startswith(f"FFmpeg {pin['version']}: ffmpeg and ffprobe")
    assert pin["url"] in text and pin["sha256"] in text
    assert "packaging/build_ffmpeg.sh" in text and "GPL-3.0.txt" in text
    assert "no third-party library is compiled in" in text
    assert f"also attached to each Discjockey release, as ffmpeg-{pin['version']}.tar.xz" in text


def shell_quoted(arg: str) -> str:
    """An argument as ffmpeg's configure prints it in the configuration line (its sh_quote): the part after the first
    '=' in single quotes when it holds anything outside [A-Za-z0-9_/.+-]."""
    name, eq, value = arg.partition("=")
    return f"{name}{eq}'{value}'" if re.search(r"[^A-Za-z0-9_/.+-]", value) else arg


def test_the_configuration_line_is_the_one_tools_json_builds_with():
    """The notice states exactly the configuration the build uses (ffmpeg -version prints the same line), and that
    configuration links no external library: issue 19 (libzvbi's GPL-2.0-only files) must not come back unnoticed."""
    _, configuration = ffmpeg_notice()
    assert configuration == "configuration: " + " ".join(shell_quoted(arg) for arg in PINS["ffmpeg"]["configure"])
    assert "--disable-autodetect" in configuration
    assert not re.search(r"--enable-(lib|openssl|gnutls|mbedtls|fontconfig)", configuration)


def test_the_built_ffmpeg_on_path_prints_the_notices_configuration():
    """In CI (and after fetch_tools.py with dist/tools/bin first on PATH) the ffmpeg on PATH is the app's own build:
    its real configuration line must be the notice's. A developer's Homebrew ffmpeg is not ours: skip."""
    exe = shutil.which("ffmpeg")
    lines = subprocess.run([exe, "-version"], capture_output=True, text=True).stdout.splitlines() if exe else []
    if not lines or "-Discjockey " not in lines[0]:
        pytest.skip("the ffmpeg on PATH is not Discjockey's build")
    _, configuration = ffmpeg_notice()
    assert configuration in lines


def test_the_repo_licence_is_the_gpl_text_byte_for_byte():
    assert (REPO / "LICENSE").read_bytes() == (PACKAGING / "licenses" / "GPL-3.0.txt").read_bytes()
    assert b"GNU GENERAL PUBLIC LICENSE" in (REPO / "LICENSE").read_bytes()


def test_the_projects_declare_their_licence():
    assert tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["license"] == "GPL-3.0-only"
    assert json.loads((REPO / "hub-ui" / "package.json").read_text())["license"] == "GPL-3.0-only"


def test_the_collected_folder_carries_the_ffmpeg_notice_and_names_the_source(tmp_path):
    out, licence = tmp_path / "out", tmp_path / "LICENSE.txt"
    licence.write_text("PSF")
    assert collect_licenses.collect(out, [], python_licence_file=licence) == []
    assert (out / "ffmpeg.txt").read_text() == (PACKAGING / "licenses" / "ffmpeg.txt").read_text()
    index = (out / "INDEX.txt").read_text()
    version = discjockey.__version__
    assert "https://github.com/TheZwiss/discjockey" in index and f"the tag v{version}" in index
    assert "-> ffmpeg.txt" in index


def test_a_hand_kept_subfolder_is_copied_whole(tmp_path):
    hand = tmp_path / "hand"
    (hand / "libs").mkdir(parents=True)
    (hand / "libs" / "zlib.txt").write_text("Zlib text")
    (hand / "ffmpeg.txt").write_text("notice")
    out = tmp_path / "out"
    licence = tmp_path / "LICENSE.txt"
    licence.write_text("PSF")
    assert collect_licenses.collect(out, [], hand, licence, version="2.5.0") == []
    assert (out / "libs" / "zlib.txt").read_text() == "Zlib text"
    index = (out / "INDEX.txt").read_text()
    assert " -> libs/" in index and "the tag v2.5.0" in index


def test_the_version_in_the_index_is_the_one_of_the_project():
    assert collect_licenses.own_version() == discjockey.__version__


def test_an_unrelated_folder_is_never_removed(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "precious.txt").write_text("keep me")
    site, hand = tmp_path / "site", tmp_path / "hand"
    site.mkdir()
    hand.mkdir()
    licence = tmp_path / "LICENSE.txt"
    licence.write_text("PSF")
    problems = collect_licenses.collect(out, md.distributions(path=[str(site)]), hand, licence)
    assert len(problems) == 1 and "refusing to replace" in problems[0]
    assert (out / "precious.txt").read_text() == "keep me" and not (out / "INDEX.txt").exists()


def test_a_folder_with_someone_elses_index_is_never_removed(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "INDEX.txt").write_text("something else\n")
    (out / "keep.txt").write_text("keep me")
    site, hand = tmp_path / "site", tmp_path / "hand"
    site.mkdir()
    hand.mkdir()
    licence = tmp_path / "LICENSE.txt"
    licence.write_text("PSF")
    problems = collect_licenses.collect(out, md.distributions(path=[str(site)]), hand, licence)
    assert len(problems) == 1 and "refusing to replace" in problems[0]
    assert (out / "INDEX.txt").read_text() == "something else\n" and (out / "keep.txt").read_text() == "keep me"


def test_a_previous_output_and_an_empty_folder_are_replaced(tmp_path):
    out, problems = run(tmp_path, lambda site: make_dist(site, "bottle", "0.13.4", {}, license_meta="MIT"))
    (out / "stale.txt").write_text("from the last run")
    site, hand = tmp_path / "site", tmp_path / "hand"
    assert collect_licenses.collect(out, md.distributions(path=[str(site)]), hand, tmp_path / "LICENSE.txt") == []
    assert not (out / "stale.txt").exists() and (out / "INDEX.txt").is_file()
    empty = tmp_path / "empty"
    empty.mkdir()
    assert collect_licenses.collect(empty, md.distributions(path=[str(site)]), hand, tmp_path / "LICENSE.txt") == []


def test_the_index_names_the_programs_with_version_and_licence(tmp_path):
    out, _ = run(tmp_path, lambda site: None, {"deno.txt": "deno notice"})
    index = (out / "INDEX.txt").read_text()
    assert "ffmpeg 9.0.2 and ffprobe 9.0.2: GPL-3.0-or-later" in index
    assert "deno 2.9.8: MIT" in index


def test_the_user_interface_runtime_is_credited():
    names = {p.stem for p in (PACKAGING / "licenses").iterdir()}
    assert {"svelte", "vite"} <= names
    label = collect_licenses.hand_kept_label("svelte")
    assert "MIT" in label and "svelte " in label


def test_a_distribution_without_a_name_is_reported_not_a_crash(tmp_path):
    def setup(site):
        info = site / "broken-1.0.dist-info"
        info.mkdir(parents=True)
        (info / "METADATA").write_text("Metadata-Version: 2.1\nVersion: 1.0\n")

    _, problems = run(tmp_path, setup)
    assert len(problems) == 1 and "has no Name" in problems[0]


def test_same_named_licence_files_do_not_overwrite_each_other(tmp_path):
    files = {f"licenses/{d}/COPYING": f"text {d}" for d in "abc"}
    out, problems = run(tmp_path, lambda site: make_dist(site, "multi", "2.0", files))
    assert problems == []
    texts = sorted(p.read_text() for p in (out / "python" / "multi-2.0").iterdir())
    assert texts == ["text a", "text b", "text c"]
