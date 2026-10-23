"""scripts/import_signing_identity.sh: the CI import of the "Discjockey Release" identity (spec public-release §6.3).
The refusals run with a `security` stand-in that fails the test if it is called at all: they touch no keychain.
The round trip makes real keychains (inside temp folders only), so it is opt-in: DISCJOCKEY_KEYCHAIN_TESTS=1."""
import os
import plistlib
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from discjockey import REPO
from packaging_helpers import load

sign_app = load("sign_app")
SCRIPT = REPO / "scripts" / "import_signing_identity.sh"
MAKE = REPO / "scripts" / "make_signing_identity.sh"
PASSWORD = "correct horse"
SECURITY_TIMEOUT = 60  # a GUI password dialog must never hang a run


def openssl3() -> str:
    exe = shutil.which("openssl") or ""
    if exe and "OpenSSL 3" in subprocess.run([exe, "version"], capture_output=True, text=True).stdout:
        return exe
    pytest.skip("needs OpenSSL 3")


@pytest.fixture
def no_keychain(tmp_path):
    """An environment whose `security` records its calls and fails: a refusal must never get that far."""
    stub = tmp_path / "stub"
    stub.mkdir()
    (stub / "security").write_text('#!/bin/bash\necho "$@" >> "$STUB_LOG"\nexit 99\n')
    (stub / "security").chmod(0o755)
    log = tmp_path / "security.log"
    env = {k: v for k, v in os.environ.items() if k not in ("SIGNING_P12_PASSWORD", "DISCJOCKEY_SIGNING_DIR")}
    env.update(PATH=f"{stub}:{os.environ['PATH']}", STUB_LOG=str(log))
    return env, log


def make_p12(tmp_path: Path, cn: str, password: str = PASSWORD, legacy: bool = True) -> Path:
    """A self-signed code-signing certificate named `cn`, as a -legacy .p12 (what make_signing_identity.sh exports)."""
    openssl = openssl3()
    safe = "".join(c if c.isalnum() else "_" for c in cn) + ("" if legacy else "_modern")
    cnf = tmp_path / f"{safe}.cnf"
    cnf.write_text(f"[req]\ndistinguished_name=dn\nx509_extensions=ext\nprompt=no\n[dn]\nCN={cn}\n"
                   "[ext]\nbasicConstraints=critical,CA:false\nkeyUsage=critical,digitalSignature\n"
                   "extendedKeyUsage=critical,codeSigning\n")
    key, cert, p12 = tmp_path / f"{safe}.key", tmp_path / f"{safe}.pem", tmp_path / f"{safe}.p12"
    subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-keyout", key,
                    "-out", cert, "-config", cnf], check=True, capture_output=True)
    subprocess.run([openssl, "pkcs12", "-export", *(["-legacy"] if legacy else []), "-inkey", key, "-in", cert,
                    "-out", p12, "-passout", f"pass:{password}"], check=True, capture_output=True)
    return p12


def run(env, *args, folder: Path | None = None, password: str | None = PASSWORD):
    env = dict(env)
    if folder is not None:
        env["DISCJOCKEY_SIGNING_DIR"] = str(folder)
    if password is not None:
        env["SIGNING_P12_PASSWORD"] = password
    return subprocess.run(["bash", str(SCRIPT), *map(str, args)], env=env, capture_output=True, text=True)


def test_a_missing_file_is_refused(tmp_path, no_keychain):
    env, log = no_keychain
    folder = tmp_path / "signing"
    r = run(env, tmp_path / "nope.p12", folder=folder)
    assert r.returncode == 1 and "does not exist" in r.stderr
    assert not folder.exists() and not log.exists()


def test_an_empty_or_unset_password_is_refused(tmp_path, no_keychain):
    env, log = no_keychain
    p12 = tmp_path / "x.p12"
    p12.write_bytes(b"not read")
    for password in ("", None):
        r = run(env, p12, folder=tmp_path / "signing", password=password)
        assert r.returncode == 1 and "SIGNING_P12_PASSWORD" in r.stderr
    assert not (tmp_path / "signing").exists() and not log.exists()


def test_an_unset_signing_folder_is_refused_with_no_default(tmp_path, no_keychain):
    env, log = no_keychain
    p12 = tmp_path / "x.p12"
    p12.write_bytes(b"not read")
    home = tmp_path / "home"
    home.mkdir()
    r = run({**env, "HOME": str(home)}, p12)
    assert r.returncode == 2 and "DISCJOCKEY_SIGNING_DIR" in r.stderr
    assert list(home.iterdir()) == [] and not log.exists()  # nothing written into a home folder


def test_a_wrong_number_of_arguments_is_a_usage_error(tmp_path, no_keychain):
    env, log = no_keychain
    assert run(env, folder=tmp_path / "signing").returncode == 2
    assert run(env, "a.p12", "b.p12", folder=tmp_path / "signing").returncode == 2
    assert not log.exists()


@pytest.mark.parametrize("existing", ["identity.sha1", "discjockey-release.keychain-db"])
def test_an_existing_identity_is_never_replaced(tmp_path, no_keychain, existing):
    env, log = no_keychain
    folder = tmp_path / "signing"
    folder.mkdir()
    (folder / existing).write_text("mine")
    p12 = tmp_path / "x.p12"
    p12.write_bytes(b"not read")
    r = run(env, p12, folder=folder)
    assert r.returncode == 1 and "already exists" in r.stderr and existing in r.stderr
    assert [p.name for p in folder.iterdir()] == [existing] and (folder / existing).read_text() == "mine"
    assert not log.exists()


def test_a_wrong_password_is_refused_before_any_keychain(tmp_path, no_keychain):
    env, log = no_keychain
    p12 = make_p12(tmp_path, "Discjockey Release")
    folder = tmp_path / "signing"
    r = run(env, p12, folder=folder, password="hunter2-guess")
    assert r.returncode == 1 and "wrong password" in r.stderr
    assert "hunter2" not in r.stderr and PASSWORD not in r.stderr  # no password is ever echoed
    assert not folder.exists() and not log.exists()


def test_a_certificate_with_another_name_is_refused_before_any_keychain(tmp_path, no_keychain):
    env, log = no_keychain
    for name in ("Apple Development: Someone Else", "Discjockey Release 2", "Not Discjockey Release"):
        p12 = make_p12(tmp_path, name)
        r = run(env, p12, folder=tmp_path / "signing")
        assert r.returncode == 1 and 'holds no "Discjockey Release" code-signing identity' in r.stderr, name
    assert not (tmp_path / "signing").exists() and not log.exists()


def test_a_p12_with_a_second_identity_is_refused_before_any_keychain(tmp_path, no_keychain):
    env, log = no_keychain
    p12 = make_p12(tmp_path, "Discjockey Release")
    two = tmp_path / "two-certs"  # an openssl stand-in whose read finds two certificates with keys
    block = "-----BEGIN CERTIFICATE-----\\nAAAA\\n-----END CERTIFICATE-----\\n"
    two.write_text(f'#!/bin/bash\nif [ "$1" = version ]; then echo "LibreSSL 3.3.6"; exit 0; fi\n'
                   f'printf -- "{block}{block}"\n')
    two.chmod(0o755)
    r = run({**env, "OPENSSL": str(two)}, p12, folder=tmp_path / "signing")
    assert r.returncode == 1 and "more than one certificate with a key" in r.stderr
    assert not (tmp_path / "signing").exists() and not log.exists()


def openssls() -> list[str]:
    """Every openssl that can matter: macOS's LibreSSL, and an OpenSSL 3 (Homebrew's or the one first on PATH)."""
    found = [e for e in ("/usr/bin/openssl", shutil.which("openssl"), "/opt/homebrew/opt/openssl@3/bin/openssl",
                         "/usr/local/opt/openssl@3/bin/openssl") if e and os.access(e, os.X_OK)]
    return list(dict.fromkeys(os.path.realpath(e) if "openssl@3" in e else e for e in found))


@pytest.mark.parametrize("legacy", [True, False], ids=["legacy-p12", "modern-p12"])
def test_the_p12_is_read_with_every_openssl(tmp_path, no_keychain, legacy):
    """Reading works (the refusal is about the name, not 'Could not open') and a wrong password is still refused,
    with LibreSSL (no -legacy flag) and OpenSSL 3 (needs -legacy for the maker's RC2/3DES file) alike."""
    env, log = no_keychain
    p12 = make_p12(tmp_path, "Not Discjockey Release", legacy=legacy)
    for exe in openssls():
        r = run({**env, "OPENSSL": exe}, p12, folder=tmp_path / "signing")
        assert r.returncode == 1 and 'holds no "Discjockey Release"' in r.stderr, (exe, r.stderr)
        r = run({**env, "OPENSSL": exe}, p12, folder=tmp_path / "signing", password="hunter2-guess")
        assert r.returncode == 1 and "Could not open" in r.stderr, (exe, r.stderr)
    default = run(env, p12, folder=tmp_path / "signing")  # no OPENSSL set: /usr/bin/openssl
    assert 'holds no "Discjockey Release"' in default.stderr
    assert not log.exists() and not (tmp_path / "signing").exists()


def test_a_file_that_is_not_a_p12_is_refused(tmp_path, no_keychain):
    env, log = no_keychain
    junk = tmp_path / "junk.p12"
    junk.write_text("hello")
    r = run(env, junk, folder=tmp_path / "signing")
    assert r.returncode == 1 and "Could not open" in r.stderr and not log.exists()


def keychain_state() -> tuple[str, str]:
    """The user keychain search list and the default keychain, as `security` prints them (every call under a timeout)."""
    def out(*cmd):
        return subprocess.run(["security", *cmd], capture_output=True, text=True, timeout=SECURITY_TIMEOUT,
                              stdin=subprocess.DEVNULL, start_new_session=True).stdout
    return out("list-keychains", "-d", "user"), out("default-keychain", "-d", "user")


def restore_keychain_list(saved: str) -> None:
    entries = [line.strip().strip('"') for line in saved.splitlines() if line.strip()]
    subprocess.run(["security", "list-keychains", "-d", "user", "-s", *entries], timeout=SECURITY_TIMEOUT,
                   stdin=subprocess.DEVNULL, start_new_session=True, check=False)


@pytest.mark.skipif(os.environ.get("DISCJOCKEY_KEYCHAIN_TESTS") != "1",
                    reason="makes real keychains (in temp folders); set DISCJOCKEY_KEYCHAIN_TESTS=1")
def test_the_import_gives_the_layout_the_maker_gives_and_signs(tmp_path):
    openssl3()
    a, b = tmp_path / "made", tmp_path / "imported"
    before = keychain_state()
    env = {k: v for k, v in os.environ.items() if k not in ("DISCJOCKEY_SIGNING_NAME", "SIGNING_P12_PASSWORD")}
    kwargs = dict(env={**env, "DISCJOCKEY_SIGNING_DIR": str(a)}, timeout=120, stdin=subprocess.DEVNULL,
                  start_new_session=True)
    try:
        subprocess.run(["bash", str(MAKE)], check=True, **kwargs)
        kwargs["env"] = {**env, "DISCJOCKEY_SIGNING_DIR": str(b),
                         "SIGNING_P12_PASSWORD": (a / "p12.pass").read_text()}
        r = subprocess.run(["bash", str(SCRIPT), str(a / "discjockey-release.p12")], capture_output=True, text=True,
                           **kwargs)
        assert r.returncode == 0, r.stderr
        # (macOS keeps a hidden `.fl…` lock file next to a keychain; it is not ours)
        assert sorted(p.name for p in b.iterdir() if not p.name.startswith(".")) == sorted(
            ["identity.sha1", "keychain.pass", sign_app.KEYCHAIN])
        assert stat.S_IMODE(b.stat().st_mode) == 0o700
        assert all(stat.S_IMODE(p.stat().st_mode) & 0o077 == 0 for p in b.iterdir() if not p.name.startswith("."))
        assert (b / "identity.sha1").read_text() == (a / "identity.sha1").read_text()
        assert (b / "keychain.pass").read_text() != (a / "keychain.pass").read_text()  # a fresh password
        assert keychain_state() == before
        found = sign_app.find_identity(b)
        assert found is not None and found.sha1 == (a / "identity.sha1").read_text().strip()

        # a second import into the same folder is refused and changes nothing
        again = subprocess.run(["bash", str(SCRIPT), str(a / "discjockey-release.p12")], capture_output=True,
                               text=True, **kwargs)
        assert again.returncode == 1 and "already exists" in again.stderr
        assert (b / "identity.sha1").read_text() == (a / "identity.sha1").read_text()

        # codesign uses the imported key without a prompt (the partition list); a dialog would hit the timeout
        app = tmp_path / "Discjockey.app"
        (app / "Contents" / "MacOS").mkdir(parents=True)
        shutil.copy(Path(sys.executable).resolve(), app / "Contents" / "MacOS" / "Discjockey")
        (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps(
            {"CFBundleExecutable": "Discjockey", "CFBundleIdentifier": "io.github.thezwiss.discjockey.test",
             "CFBundlePackageType": "APPL"}))
        signed = subprocess.run([sys.executable, str(REPO / "packaging" / "sign_app.py"), "--require-identity",
                                 str(app)], capture_output=True, text=True, **kwargs)
        assert signed.returncode == 0, signed.stderr
        assert keychain_state() == before
    finally:
        for folder in (a, b):
            subprocess.run(["security", "delete-keychain", str(folder / sign_app.KEYCHAIN)], check=False,
                           capture_output=True, timeout=SECURITY_TIMEOUT, stdin=subprocess.DEVNULL,
                           start_new_session=True)
        after = keychain_state()
        if after[0] != before[0]:
            restore_keychain_list(before[0])
        assert keychain_state() == before
