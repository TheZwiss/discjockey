import os
import subprocess

import pytest

from packaging_helpers import load

machos = load("machos")
HEAD = b"\xcf\xfa\xed\xfe" + b"\0" * 28

FFMPEG = """x/ffmpeg:
Load command 12
      cmd LC_BUILD_VERSION
  cmdsize 32
 platform MACOS
    minos 12.0
      sdk 12.3
   ntools 1
     tool LD
  version 819.6
"""
NUMPY = FFMPEG.replace("minos 12.0", "minos 14.0").replace("version 819.6", "version 1053.12")
OLD = """old.so:
Load command 9
      cmd LC_VERSION_MIN_MACOSX
  cmdsize 16
  version 10.13
      sdk 10.14
"""


def answers(by_name: dict[str, str]):
    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, by_name.get(cmd[-1].rsplit("/", 1)[-1], ""), "")
    return run


def fake_app(tmp_path):
    app = tmp_path / "Discjockey.app"
    for rel in ("Contents/MacOS/Discjockey", "Contents/Frameworks/bin/ffmpeg", "Contents/Frameworks/numpy/core.so"):
        (app / rel).parent.mkdir(parents=True, exist_ok=True)
        (app / rel).write_bytes(HEAD)
    (app / "Contents/Resources").mkdir(parents=True)
    (app / "Contents/Resources/bin").symlink_to("../Frameworks/bin")
    (app / "Contents/Resources/x.py").write_text("print()")
    (app / "Contents/Resources/Foo.class").write_bytes(b"\xca\xfe\xba\xbe\x00\x00\x00\x34")
    return app


def test_only_real_mach_o_files_count(tmp_path):
    app = fake_app(tmp_path)
    assert [p.relative_to(app).as_posix() for p in machos.macho_files(app)] == [
        "Contents/Frameworks/bin/ffmpeg", "Contents/Frameworks/numpy/core.so", "Contents/MacOS/Discjockey"]


def test_minos_reads_build_version_not_the_linker_version(tmp_path):
    assert machos.minos(tmp_path / "ffmpeg", answers({"ffmpeg": FFMPEG})) == ["12.0"]
    assert machos.minos(tmp_path / "old.so", answers({"old.so": OLD})) == ["10.13"]


def test_too_new_flags_a_macos_14_library(tmp_path):
    app = fake_app(tmp_path)
    run = answers({"ffmpeg": FFMPEG, "core.so": NUMPY, "Discjockey": FFMPEG})
    assert machos.too_new(app, "12.0", run) == ["Contents/Frameworks/numpy/core.so: needs macOS 14.0"]


def test_a_file_without_a_minimum_is_flagged(tmp_path):
    app = fake_app(tmp_path)
    run = answers({"ffmpeg": FFMPEG, "core.so": FFMPEG})
    assert machos.too_new(app, "12.0", run) == ["Contents/MacOS/Discjockey: no minimum macOS found"]


def test_fat_binaries_count_but_java_class_files_do_not(tmp_path):
    fat, java = tmp_path / "fat", tmp_path / "Foo.class"
    fat.write_bytes(b"\xca\xfe\xba\xbe\x00\x00\x00\x02" + b"\0" * 40)  # two architectures
    java.write_bytes(b"\xca\xfe\xba\xbe\x00\x00\x00\x34")  # class version 52
    assert machos.is_macho(fat) and not machos.is_macho(java)


def test_the_highest_minimum_of_a_universal_binary_counts(tmp_path):
    two = FFMPEG + FFMPEG.replace("minos 12.0", "minos 13.1").split("x/ffmpeg:\n")[1]
    assert machos.minos(tmp_path / "ffmpeg", answers({"ffmpeg": two})) == ["12.0", "13.1"]
    assert machos.key("13.1") > machos.key("12.0") and machos.key("12.10") > machos.key("12.9")


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads anything")
def test_an_unreadable_file_is_an_error_not_a_skip(tmp_path, capsys):
    app = fake_app(tmp_path)
    secret = app / "Contents/Frameworks/numpy/core.so"
    secret.chmod(0)
    try:
        with pytest.raises(PermissionError):
            machos.macho_files(app)
        assert machos.main(["minos", str(app)]) == 1
        assert "minos:" in capsys.readouterr().err
    finally:
        secret.chmod(0o644)


def test_a_missing_vtool_is_a_clear_failure(tmp_path, monkeypatch, capsys):
    def run(cmd, **kw):
        raise FileNotFoundError(2, "No such file or directory", "vtool")
    real = machos.too_new
    monkeypatch.setattr(machos, "too_new", lambda app, maximum: real(app, maximum, run))
    assert machos.main(["minos", str(fake_app(tmp_path))]) == 1
    assert "vtool" in capsys.readouterr().err
