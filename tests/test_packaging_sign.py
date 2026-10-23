import os
import plistlib
import shutil
import signal
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from discjockey import REPO
from packaging_helpers import load

sign_app = load("sign_app")
HEAD = b"\xcf\xfa\xed\xfe" + b"\0" * 28
SHA1 = "93FB6FD41FBECE9FFC89D5BC40EFD1BB6F2DE058"
LOGIN = "/Users/someone/Library/Keychains/login.keychain-db"
SCRIPT = REPO / "scripts" / "make_signing_identity.sh"


class FakeMac:
    """Stands in for subprocess.run: records commands, keeps a keychain search list, lists identities."""

    def __init__(self, listing: str = "", fail_on: str | None = None, fail_unlock: bool = False, on_sign=None):
        self.calls, self.keychains, self.listing, self.fail_on = [], [LOGIN], listing, fail_on
        self.fail_unlock, self.on_sign = fail_unlock, on_sign
        self.list_while_signing, self.kwargs = [], []

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))
        self.kwargs.append(kw)
        out, rc, err = "", 0, "boom"
        if cmd[:4] == ["security", "list-keychains", "-d", "user"]:
            if "-s" in cmd:
                self.keychains = list(cmd[cmd.index("-s") + 1:])
            else:
                out = "".join(f'    "{k}"\n' for k in self.keychains)
        elif cmd[:2] == ["security", "unlock-keychain"] and self.fail_unlock:
            rc, err = 51, f"could not unlock (the keychain password was {kw.get('input', '').strip()})"
        elif cmd[:2] == ["security", "find-identity"]:
            out = self.listing
        elif cmd[0] == "codesign" and "--sign" in cmd:
            self.list_while_signing.append(list(self.keychains))
            if self.on_sign:
                self.on_sign()
            if self.fail_on and cmd[-1].endswith(self.fail_on):
                rc = 1
        elif cmd[:2] == ["codesign", "-d"]:
            out = f'designated => identifier "x" and certificate leaf = H"{SHA1.lower()}"\n'
        return subprocess.CompletedProcess(cmd, rc, out, err)


def fake_app(tmp_path: Path) -> Path:
    app = tmp_path / "Disc jockey build" / "Discjockey.app"  # a space, like the real checkout path
    for rel in ("Contents/MacOS/Discjockey", "Contents/Frameworks/bin/ffmpeg",
                "Contents/Frameworks/PIL/__dot__dylibs/libwebp.dylib", "Contents/Frameworks/libpython3.12.dylib"):
        (app / rel).parent.mkdir(parents=True, exist_ok=True)
        (app / rel).write_bytes(HEAD)
    return app


def identity(tmp_path) -> "sign_app.Identity":
    return sign_app.Identity(SHA1, sign_app.NAME, tmp_path / sign_app.KEYCHAIN, "pw")


def test_inside_out_order(tmp_path):
    app = fake_app(tmp_path)
    order = [p.relative_to(app.parent).as_posix() for p in sign_app.sign_order(app)]
    assert order == ["Discjockey.app/Contents/Frameworks/PIL/__dot__dylibs/libwebp.dylib",
                     "Discjockey.app/Contents/Frameworks/bin/ffmpeg",
                     "Discjockey.app/Contents/Frameworks/libpython3.12.dylib",
                     "Discjockey.app/Contents/MacOS/Discjockey", "Discjockey.app"]


def test_signing_names_only_our_sha1_and_keychain(tmp_path):
    app, mac, me = fake_app(tmp_path), FakeMac(), identity(tmp_path)
    assert sign_app.sign(app, me, mac) == 5
    signs = [c for c in mac.calls if c[0] == "codesign"]
    assert all(c[c.index("--sign") + 1] == SHA1 and c[c.index("--keychain") + 1] == str(me.keychain) for c in signs)
    assert all("--options" not in c and "--timestamp=none" in c and "--force" in c for c in signs)
    assert not any("Apple Development" in " ".join(c) for c in mac.calls)
    assert all(lst == [LOGIN, str(me.keychain)] for lst in mac.list_while_signing)
    assert mac.keychains == [LOGIN]


def test_a_failed_signing_puts_the_search_list_back(tmp_path):
    app, mac = fake_app(tmp_path), FakeMac(fail_on="Contents/MacOS/Discjockey")
    with pytest.raises(sign_app.SigningError, match="codesign"):
        sign_app.sign(app, identity(tmp_path), mac)
    assert mac.keychains == [LOGIN]


def test_ad_hoc_touches_no_keychain(tmp_path):
    app, mac = fake_app(tmp_path), FakeMac()
    sign_app.sign(app, sign_app.AD_HOC, mac)
    assert not any(c[0] == "security" for c in mac.calls)
    assert all(c[c.index("--sign") + 1] == "-" and "--keychain" not in c for c in mac.calls if c[0] == "codesign")


def test_find_identity_ignores_other_identities(tmp_path):
    folder = tmp_path / "signing"
    folder.mkdir()
    for name, text in ((sign_app.KEYCHAIN, ""), ("identity.sha1", SHA1 + "\n"), ("keychain.pass", "pw")):
        (folder / name).write_text(text)
    other = '  1) 1111111111111111111111111111111111111111 "Apple Development: Sam Rivers (ABCDE12345)"\n'
    found = sign_app.find_identity(folder, sign_app.NAME, FakeMac(other + f'  2) {SHA1} "Discjockey Release"\n'))
    assert found == sign_app.Identity(SHA1, sign_app.NAME, folder / sign_app.KEYCHAIN, "pw")
    with pytest.raises(sign_app.SigningError):
        sign_app.find_identity(folder, sign_app.NAME, FakeMac(other))


def identity_folder(tmp_path, sha1: str = SHA1) -> Path:
    folder = tmp_path / "signing"
    folder.mkdir()
    for name, text in ((sign_app.KEYCHAIN, ""), ("identity.sha1", sha1 + "\n"), ("keychain.pass", "pw")):
        (folder / name).write_text(text)
    return folder


def test_the_password_goes_to_security_on_stdin_not_in_the_command(tmp_path):
    mac = FakeMac(f'  1) {SHA1} "Discjockey Release"\n')
    sign_app.find_identity(identity_folder(tmp_path), sign_app.NAME, mac)
    unlock = [(c, kw) for c, kw in zip(mac.calls, mac.kwargs) if c[:2] == ["security", "unlock-keychain"]]
    assert len(unlock) == 1 and unlock[0][1]["input"] == "pw\n" and unlock[0][1]["start_new_session"]
    assert unlock[0][0] == ["security", "unlock-keychain", str(tmp_path / "signing" / sign_app.KEYCHAIN)]
    assert not any("pw" in c for c in mac.calls)


def test_a_failed_unlock_never_prints_the_password_or_the_command(tmp_path, monkeypatch, capsys):
    folder = identity_folder(tmp_path)
    mac = FakeMac(fail_unlock=True)
    with pytest.raises(sign_app.SigningError) as raised:
        sign_app.find_identity(folder, sign_app.NAME, mac)
    assert "pw" not in str(raised.value) and "security" not in str(raised.value) and "unlock" in str(raised.value)
    monkeypatch.setenv("DISCJOCKEY_SIGNING_DIR", str(folder))
    assert sign_app.main([str(fake_app(tmp_path)), "--require-identity"], mac) == 1
    shown = capsys.readouterr()
    assert "pw" not in shown.out + shown.err and "sign_app:" in shown.err


def test_a_failing_search_list_command_does_not_show_its_command(tmp_path):
    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", "denied")
    with pytest.raises(sign_app.SigningError) as raised:
        sign_app.search_list(run)
    assert str(raised.value) == "reading the keychain search list failed: denied"


def test_an_identity_never_shows_its_password(tmp_path):
    assert "pw" not in repr(sign_app.Identity("A" * 40, "n", None, "pw"))


@pytest.mark.parametrize("sha1", ["", "93FB6FD4", "93FB6FD41FBECE9FFC89D5BC40EFD1BB6F2DE05G", "0" + SHA1])
def test_a_malformed_identity_sha1_is_refused(tmp_path, sha1):
    mac = FakeMac(f'  1) {sha1} "Discjockey Release"\n  2) {SHA1} "Discjockey Release"\n')
    with pytest.raises(sign_app.SigningError, match="40-character"):
        sign_app.find_identity(identity_folder(tmp_path, sha1), sign_app.NAME, mac)
    assert mac.calls == []  # refused before any security command


def test_sigterm_during_signing_puts_the_search_list_back(tmp_path):
    app = fake_app(tmp_path)
    mac = FakeMac(on_sign=lambda: os.kill(os.getpid(), signal.SIGTERM))
    before = signal.getsignal(signal.SIGTERM)
    with pytest.raises(SystemExit) as raised:
        sign_app.sign(app, identity(tmp_path), mac)
    assert raised.value.code == 128 + signal.SIGTERM
    assert mac.keychains == [LOGIN]
    assert signal.getsignal(signal.SIGTERM) == before


def test_no_identity_folder_means_none(tmp_path):
    assert sign_app.find_identity(tmp_path / "nothing", sign_app.NAME, FakeMac()) is None


def test_a_missing_codesign_is_a_clear_failure(tmp_path, monkeypatch, capsys):
    def run(cmd, **kw):
        raise FileNotFoundError(2, "No such file or directory", cmd[0])
    assert sign_app.main([str(fake_app(tmp_path)), "--adhoc"], run) == 1
    assert "codesign" in capsys.readouterr().err


def test_a_release_build_refuses_ad_hoc(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DISCJOCKEY_SIGNING_DIR", str(tmp_path / "nothing"))
    assert sign_app.main([str(fake_app(tmp_path)), "--require-identity"]) == 1
    assert "make_signing_identity.sh" in capsys.readouterr().err


def test_the_identity_script_never_replaces_an_identity(tmp_path):
    folder = tmp_path / "signing"
    folder.mkdir()
    (folder / "identity.sha1").write_text(SHA1)
    r = subprocess.run(["bash", str(SCRIPT)], env={**os.environ, "DISCJOCKEY_SIGNING_DIR": str(folder)},
                       capture_output=True, text=True)
    assert r.returncode == 1 and "already exists" in r.stderr and "(identity.sha1)" in r.stderr
    assert sorted(p.name for p in folder.iterdir()) == ["identity.sha1"]


def test_the_identity_script_refuses_when_only_the_keychain_exists(tmp_path):
    folder = tmp_path / "signing"
    folder.mkdir()
    (folder / sign_app.KEYCHAIN).write_text("")
    r = subprocess.run(["bash", str(SCRIPT)], env={**os.environ, "DISCJOCKEY_SIGNING_DIR": str(folder)},
                       capture_output=True, text=True)
    assert r.returncode == 1 and "already exists" in r.stderr and sign_app.KEYCHAIN in r.stderr
    assert sorted(p.name for p in folder.iterdir()) == [sign_app.KEYCHAIN]


STUB = """#!/bin/bash
# stands in for `security`: a search list kept in a file, create-keychain adds to it, import fails
echo "$@" >> "$STUB_DIR/log"
case "$1 $2" in
  "list-keychains -d")
    if [ "${4:-}" = "-s" ]; then : > "$STUB_DIR/list"; for k in "${@:5}"; do echo "$k" >> "$STUB_DIR/list"; done
    else while IFS= read -r k; do echo "    \"$k\""; done < "$STUB_DIR/list"; fi ;;
  "default-keychain -d") echo '    "/Users/someone/Library/Keychains/login.keychain-db"' ;;
  "create-keychain -p") echo "${@: -1}" >> "$STUB_DIR/list"; : > "${@: -1}" ;;
  "import "*) exit 1 ;;
  "delete-keychain "*) rm -f "$2" ;;
  *) ;;
esac
"""


def test_a_failed_identity_script_restores_the_search_list_and_leaves_nothing(tmp_path):
    openssl = shutil.which("openssl")
    if not openssl or "OpenSSL 3" not in subprocess.run([openssl, "version"], capture_output=True, text=True).stdout:
        pytest.skip("needs OpenSSL 3")
    stub_dir, folder = tmp_path / "stub", tmp_path / "signing"
    stub_dir.mkdir()
    (stub_dir / "security").write_text(STUB)
    (stub_dir / "security").chmod(0o755)
    (stub_dir / "list").write_text(LOGIN + "\n")
    env = {**os.environ, "PATH": f"{stub_dir}:{os.environ['PATH']}", "STUB_DIR": str(stub_dir),
           "DISCJOCKEY_SIGNING_DIR": str(folder)}
    r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert r.returncode != 0 and "Run this again" in r.stderr
    assert (stub_dir / "list").read_text() == LOGIN + "\n"  # the keychain create-keychain added is off the list
    assert not folder.exists()  # created by this run, so removed again: nothing blocks the next run
    log = (stub_dir / "log").read_text()
    assert "-p " not in log.split("unlock-keychain")[1].split("\n")[0]  # unlock got no password argument


def test_a_failed_identity_script_keeps_a_folder_it_did_not_make(tmp_path):
    openssl = shutil.which("openssl")
    if not openssl or "OpenSSL 3" not in subprocess.run([openssl, "version"], capture_output=True, text=True).stdout:
        pytest.skip("needs OpenSSL 3")
    stub_dir, folder = tmp_path / "stub", tmp_path / "signing"
    stub_dir.mkdir()
    folder.mkdir()
    (folder / "notes.txt").write_text("mine")
    (stub_dir / "security").write_text(STUB)
    (stub_dir / "security").chmod(0o755)
    (stub_dir / "list").write_text(LOGIN + "\n")
    env = {**os.environ, "PATH": f"{stub_dir}:{os.environ['PATH']}", "STUB_DIR": str(stub_dir),
           "DISCJOCKEY_SIGNING_DIR": str(folder)}
    r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert r.returncode != 0 and "Delete the files this run made" in r.stderr
    assert (folder / "notes.txt").read_text() == "mine"  # a folder this run did not make is never removed
    assert (stub_dir / "list").read_text() == LOGIN + "\n"
    assert not (folder / sign_app.KEYCHAIN).exists()


@pytest.mark.skipif(os.environ.get("DISCJOCKEY_KEYCHAIN_TESTS") != "1",
                    reason="makes a real keychain; set DISCJOCKEY_KEYCHAIN_TESTS=1")
def test_a_real_identity_signs_the_same_way_twice(tmp_path):
    folder, name = tmp_path / "signing", "Discjockey Test"
    before = sign_app.search_list()
    env = {**os.environ, "DISCJOCKEY_SIGNING_DIR": str(folder), "DISCJOCKEY_SIGNING_NAME": name}
    subprocess.run(["bash", str(SCRIPT)], env=env, check=True)
    try:
        assert sign_app.search_list() == before
        assert stat.S_IMODE(folder.stat().st_mode) == 0o700
        assert all(stat.S_IMODE(p.stat().st_mode) & 0o077 == 0 for p in folder.iterdir())
        me = sign_app.find_identity(folder, name)
        app = tmp_path / "Discjockey.app"
        (app / "Contents" / "MacOS").mkdir(parents=True)
        (app / "Contents" / "Frameworks" / "bin").mkdir(parents=True)
        python = Path(sys.executable).resolve()  # an arm64 Mach-O to sign
        shutil.copy(python, app / "Contents" / "MacOS" / "Discjockey")
        shutil.copy(python, app / "Contents" / "Frameworks" / "bin" / "tool")
        (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps(
            {"CFBundleExecutable": "Discjockey", "CFBundleIdentifier": "io.github.thezwiss.discjockey.test",
             "CFBundlePackageType": "APPL"}))
        sign_app.sign(app, me)
        first = sign_app.verify(app, me)
        sign_app.sign(app, me)
        assert sign_app.verify(app, me) == first and f'certificate leaf = H"{me.sha1.lower()}"' in first
        assert sign_app.search_list() == before
    finally:
        subprocess.run(["security", "delete-keychain", str(folder / sign_app.KEYCHAIN)], check=False)
        assert sign_app.search_list() == before
