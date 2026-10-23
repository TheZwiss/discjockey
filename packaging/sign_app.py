"""Signs Discjockey.app inside-out (spec public-release §6.3): every nested Mach-O file deepest first, then
Contents/MacOS/Discjockey, then the bundle. --force (PyInstaller ad-hoc signed everything), no timestamp, no hardened
runtime (only notarization needs it; its library validation would reject self-signed libraries).

The identity is the self-signed "Discjockey Release" made by scripts/make_signing_identity.sh, taken ONLY from its own
keychain (DISCJOCKEY_SIGNING_DIR, default ~/.discjockey-signing) and named by its SHA-1, never by a name search: a Mac
may hold other people's identities, and codesign must never pick one of them. Without that identity the app is signed
ad-hoc ("-"): it runs, but the keychain and Full Disk Access grants don't survive an update. --require-identity
(release builds) fails instead.

codesign only finds identities in keychains on the user search list, so the identity's keychain is added for the
signing and the list is put back exactly as it was afterwards, also when signing fails or the process gets SIGTERM
or SIGHUP (CI cancel, closed terminal).

The keychain password goes to `security` on stdin, never on its command line (it would show in `ps`), and no error
message carries a command line or the password.

usage: python packaging/sign_app.py <Discjockey.app> [--require-identity | --adhoc]"""
from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import machos  # noqa: E402

NAME = "Discjockey Release"
DIR_ENV, NAME_ENV = "DISCJOCKEY_SIGNING_DIR", "DISCJOCKEY_SIGNING_NAME"
KEYCHAIN = "discjockey-release.keychain-db"


class SigningError(Exception):
    pass


@dataclass(frozen=True)
class Identity:
    sha1: str  # "-" for ad-hoc
    name: str
    keychain: Path | None
    password: str | None = field(repr=False)  # never in a repr, traceback or assertion diff

    @property
    def adhoc(self) -> bool:
        return self.sha1 == "-"


AD_HOC = Identity("-", "ad-hoc", None, None)


def signing_dir(environ=os.environ) -> Path:
    return Path(environ.get(DIR_ENV) or Path.home() / ".discjockey-signing").expanduser()


SHA1_RE = re.compile(r"[0-9A-F]{40}")


def secure(run, cmd: list[str], what: str, secret: str | None = None, **kw) -> str:
    """Runs a `security` command and returns its output. Failure raises SigningError naming `what` and the command's
    own error text, never the command line or `secret` (CalledProcessError's message would carry the argv)."""
    r = run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        detail = (r.stderr or "").strip()
        if secret:
            detail = detail.replace(secret, "***")
        raise SigningError(f"{what} failed" + (f": {detail}" if detail else ""))
    return r.stdout or ""


def find_identity(folder: Path, name: str = NAME, run=subprocess.run) -> Identity | None:
    """The identity in `folder`, checked to be in its own keychain under that SHA-1 and name. None: the folder has
    none. SigningError: the folder says one exists but its keychain doesn't hold it."""
    kc, sha_file, pw_file = folder / KEYCHAIN, folder / "identity.sha1", folder / "keychain.pass"
    if not (kc.exists() and sha_file.exists() and pw_file.exists()):
        return None
    sha1, password = sha_file.read_text().strip().upper(), pw_file.read_text().strip()
    if not SHA1_RE.fullmatch(sha1):
        raise SigningError(f"{sha_file} is not a 40-character SHA-1")
    # the password on stdin; its own session so security can't ask a terminal instead
    secure(run, ["security", "unlock-keychain", str(kc)], f"unlocking {kc}", password,
           input=password + "\n", start_new_session=True)
    listing = secure(run, ["security", "find-identity", "-p", "codesigning", str(kc)], f"listing the identities in {kc}")
    if f'{sha1} "{name}"' not in listing:
        raise SigningError(f'{kc} holds no code-signing identity {sha1} "{name}"')
    return Identity(sha1, name, kc, password)


def search_list(run=subprocess.run) -> list[str]:
    out = secure(run, ["security", "list-keychains", "-d", "user"], "reading the keychain search list")
    return [line.strip().strip('"') for line in out.splitlines() if line.strip()]


@contextmanager
def on_search_list(keychain: Path | None, run=subprocess.run):
    before = search_list(run) if keychain is not None else []
    if keychain is None or str(keychain) in before:
        yield
        return
    ends = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGHUP)}
    try:
        for s in ends:
            signal.signal(s, lambda number, frame: sys.exit(128 + number))  # so the finally below runs
    except ValueError:  # not the main thread: signal handlers can't be set
        ends = {}
    try:
        secure(run, ["security", "list-keychains", "-d", "user", "-s", *before, str(keychain)],
               "adding the keychain to the search list")
        yield
    finally:
        try:
            secure(run, ["security", "list-keychains", "-d", "user", "-s", *before],
                   "restoring the keychain search list")
        finally:
            for s, old in ends.items():
                signal.signal(s, old)


def sign_order(app: Path) -> list[Path]:
    main = app / "Contents" / "MacOS" / app.stem
    nested = [p for p in machos.macho_files(app) if p != main]
    nested.sort(key=lambda p: (-len(p.relative_to(app).parts), str(p)))
    return [*nested, main, app]


def codesign_cmd(path: Path, identity: Identity) -> list[str]:
    cmd = ["codesign", "--force", "--sign", identity.sha1, "--timestamp=none"]
    if identity.keychain is not None:
        cmd += ["--keychain", str(identity.keychain)]
    return [*cmd, str(path)]


def sign(app: Path, identity: Identity, run=subprocess.run) -> int:
    order = sign_order(app)
    with on_search_list(identity.keychain, run):
        for path in order:
            r = run(codesign_cmd(path, identity), capture_output=True, text=True)
            if r.returncode != 0:
                raise SigningError(f"codesign {path}: {(r.stderr or '').strip()}")
    return len(order)


def designated_requirement(app: Path, run=subprocess.run) -> str:
    r = run(["codesign", "-d", "-r-", str(app)], capture_output=True, text=True)
    for line in (r.stdout + r.stderr).splitlines():
        if line.startswith("designated =>"):
            return line.removeprefix("designated =>").strip()
    raise SigningError(f"no designated requirement for {app}: {(r.stdout + r.stderr).strip()}")


def verify(app: Path, identity: Identity, run=subprocess.run) -> str:
    r = run(["codesign", "--verify", "--deep", "--strict", str(app)], capture_output=True, text=True)
    if r.returncode != 0:
        raise SigningError(f"codesign --verify: {(r.stderr or '').strip()}")
    dr = designated_requirement(app, run)
    if not identity.adhoc and f'certificate leaf = H"{identity.sha1.lower()}"' not in dr:
        raise SigningError(f"the app's designated requirement doesn't name {identity.name}: {dr}")
    return dr


def main(argv: list[str] | None = None, run=subprocess.run) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("app", type=Path)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--require-identity", action="store_true")
    mode.add_argument("--adhoc", action="store_true")
    a = p.parse_args(argv)
    folder, name = signing_dir(), os.environ.get(NAME_ENV) or NAME
    try:
        identity = AD_HOC if a.adhoc else find_identity(folder, name, run)
        if identity is None:
            if a.require_identity:
                print(f'No "{name}" identity in {folder}; scripts/make_signing_identity.sh makes it.', file=sys.stderr)
                return 1
            print(f'warning: no "{name}" identity in {folder}: signing ad-hoc. Keychain and Full Disk Access '
                  "grants won't survive an update of this build.", file=sys.stderr)
            identity = AD_HOC
        n = sign(a.app, identity, run)
        dr = verify(a.app, identity, run)
    except (SigningError, OSError) as e:
        print(f"sign_app: {e}", file=sys.stderr)
        return 1
    print(f"  signed {n} files with {identity.name} ({identity.sha1})")
    print(f"  designated requirement: {dr}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
