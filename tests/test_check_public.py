"""scripts/check_public.sh: the check that the tree holds no personal data (phase 6). Every forbidden sample is built
from pieces at runtime, so this file passes its own check; the names are made-up stand-ins."""
import importlib.util
import os
import shutil
import subprocess
import sys

import pytest

from discjockey import REPO

SCRIPTS = REPO / "scripts"
SH = SCRIPTS / "check_public.sh"

_spec = importlib.util.spec_from_file_location("check_public", SCRIPTS / "check_public.py")
cp = importlib.util.module_from_spec(_spec)
sys.modules["check_public"] = cp
_spec.loader.exec_module(cp)

HOME = "/Us" + "ers/"  # "/Users/", built so no sample appears whole in this file
PERSON = HOME + "jane"  # a made-up person
AT = "@"
HANDLE = "The" + "Zwiss"
STAND_IN = "Sample"  # the denylist word in these tests


def scan_one(text: str, denylist=(), path="a.txt", data=None):
    raw = data if data is not None else text.encode()
    return cp.scan([(path, raw)], list(denylist))


def rules(findings):
    return [(f.line, f.rule) for f in findings]


# ---- home-path

def test_home_path_finds_a_real_name_with_path_and_line():
    findings = scan_one(f"ok\nsee {PERSON}/Music\n")
    assert findings == [cp.Finding("a.txt", 2, "home-path", PERSON)]


@pytest.mark.parametrize("name", ["you", "dj", "someone", "x", "Shared"])
def test_home_path_allows_the_placeholder_names(name):
    assert scan_one(f"{HOME}{name}/Music") == []


def test_home_path_ignores_a_sentence_ending_dot_or_dash():
    assert scan_one(f"Put it in {HOME}you. Then {HOME}dj- and {HOME}x...") == []
    assert scan_one(f"see {PERSON}.") == [cp.Finding("a.txt", 1, "home-path", PERSON)]


def test_home_path_allows_the_bare_users_folder():
    assert scan_one(f"under {HOME} and {HOME}<name>/Music") == []


# ---- email

def test_email_finds_an_outside_address():
    findings = scan_one(f"write jane{AT}uni.edu now")
    assert findings == [cp.Finding("a.txt", 1, "email", f"jane{AT}uni.edu")]


@pytest.mark.parametrize("address", [
    f"jane{AT}github.com", f"git{AT}evil.github.com", f"jane{AT}163.com", f"jane{AT}12.uni.edu",
    f"jane{AT}notexample.com", f"jane{AT}users.noreply.github.com.evil.io",
])
def test_email_catches_look_alikes_and_numeric_providers(address):
    assert rules(scan_one(f"see {address} here")) == [(1, "email")]


@pytest.mark.parametrize("address", [
    f"a{AT}example.com", f"a{AT}example.org", f"a{AT}example.net", f"a{AT}mail.example.com",
    f"12345+{HANDLE}{AT}users.noreply.github.com", f"a{AT}host.invalid", f"a{AT}host.test", f"a{AT}host.example",
    f"git{AT}github.com", f"GIT{AT}GitHub.com", f"shot{AT}1280.png", f"icon{AT}2x.png", f"logo{AT}site.SVG",
    f"pkg{AT}1.2.3", f"name{AT}v1.2",
])
def test_email_allows_the_permitted_forms(address):
    assert scan_one(f"see {address} here") == []


# ---- repo-url

def test_repo_url_finds_another_repo():
    url = f"https://github.com/{HANDLE}/old-private"
    findings = scan_one(f"clone {url}")
    assert findings == [cp.Finding("a.txt", 1, "repo-url", f"{HANDLE}/old-private")]


def test_repo_url_is_case_insensitive():
    assert rules(scan_one(f"{HANDLE.lower()}/other")) == [(1, "repo-url")]


@pytest.mark.parametrize("text", [
    f"{HANDLE}/discjockey",
    f"api.github.com/repos/{HANDLE}/discjockey/releases/latest",
    f"https://github.com/{HANDLE}/Discjockey.git",
    f"api.github.com/repos/{HANDLE} alone",
    f"by {HANDLE}",
])
def test_repo_url_allows_the_public_repo_and_bare_handle(text):
    assert scan_one(text) == []


# ---- denylist

def test_denylist_reports_the_entry_number_not_the_word(tmp_path, capsys, monkeypatch):
    (tmp_path / "tree").mkdir()
    (tmp_path / "tree" / "f.txt").write_text(f"hello {STAND_IN} there\n")
    deny = tmp_path / "deny"
    deny.write_text(f"# comment\n\nother\n{STAND_IN}\n")
    monkeypatch.setenv(cp.DENYLIST_ENV, str(deny))
    assert cp.main(["--dir", str(tmp_path / "tree")]) == 1
    out = capsys.readouterr()
    assert "f.txt:1: denylist: denylist entry 2" in out.out
    assert STAND_IN.lower() not in (out.out + out.err).lower()


def test_denylist_is_case_insensitive_and_whole_word():
    assert rules(scan_one("a sample b", [STAND_IN])) == [(1, "denylist")]
    assert rules(scan_one("A SAMPLE.", [STAND_IN])) == [(1, "denylist")]
    assert scan_one("many samples here", [STAND_IN]) == []
    assert scan_one("resample", [STAND_IN]) == []


def test_denylist_entry_with_a_non_word_end_matches_literally():
    assert rules(scan_one("mail jane.d+x@ now", ["jane.d+x@"])) == [(1, "denylist")]


def test_denylist_file_ignores_comments_and_blank_lines(tmp_path):
    path = tmp_path / "deny"
    path.write_text("# header\n\none\n  # indented comment\ntwo  \n")
    assert cp.load_denylist(path) == ["one", "two"]
    assert cp.load_denylist(tmp_path / "missing") is None


# ---- paths and binary files

def test_a_path_with_a_denylist_word_is_a_finding_on_line_zero():
    findings = scan_one("clean", [STAND_IN], path=f"docs/{STAND_IN.lower()}-notes.md")
    assert findings == [cp.Finding(f"docs/{STAND_IN.lower()}-notes.md", 0, "denylist", "denylist entry 1")]


def test_a_path_with_a_home_path_is_a_finding_on_line_zero():
    assert rules(scan_one("clean", path=f"x{PERSON}.txt")) == [(0, "home-path")]


def test_binary_file_skips_email_but_keeps_the_other_rules():
    blob = b"\x89PNG\0\0" + f"zz jane{AT}uni.edu zz".encode()
    assert scan_one("", data=blob) == []
    with_path = b"\x89PNG\0\0" + f"tEXt{PERSON}/Music".encode()
    assert rules(scan_one("", data=with_path)) == [(1, "home-path")]
    with_word = b"\x89PNG\0\0 " + STAND_IN.encode() + b" "
    assert rules(scan_one("", [STAND_IN], data=with_word)) == [(1, "denylist")]


def test_text_file_with_a_late_nul_is_still_text():
    data = b"a" * 9000 + b"\0" + f" jane{AT}uni.edu".encode()
    assert rules(scan_one("", data=data)) == [(1, "email")]


def test_non_ascii_denylist_entry_matches_utf8_text_in_a_binary_file():
    entry = "Ren\u00e9e"
    blob = b"\x89PNG\0\0iTXt " + entry.encode("utf-8") + b" end"
    assert rules(scan_one("", [entry], data=blob)) == [(1, "denylist")]
    assert rules(scan_one(f"x {entry} y", [entry])) == [(1, "denylist")]  # a text file still matches as text


# ---- the command

def run_sh(*args, denylist=None, cwd=None, script=SH):
    env = dict(os.environ)
    env.pop(cp.DENYLIST_ENV, None)
    if denylist is not None:
        env[cp.DENYLIST_ENV] = str(denylist)
    return subprocess.run([str(script), *args], capture_output=True, text=True, env=env, cwd=cwd, timeout=60)


@pytest.fixture
def empty_denylist(tmp_path):
    path = tmp_path / "empty-denylist"
    path.write_text("# nothing\n")
    return path


def test_clean_tree_exits_0(tmp_path, empty_denylist):
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "a.txt").write_text(f"{HOME}you/Music\n")
    result = run_sh("--dir", str(tree), denylist=empty_denylist)
    assert result.returncode == 0
    assert result.stdout.strip() == "public check: clean (1 files, denylist: loaded 0 entries)"


def test_findings_exit_1_and_end_with_the_count(tmp_path, empty_denylist):
    tree = tmp_path / "tree"
    (tree / "sub").mkdir(parents=True)
    (tree / "sub" / "a.txt").write_text(f"ok\n{PERSON}/x\njane{AT}uni.edu\n")
    result = run_sh("--dir", str(tree), denylist=empty_denylist)
    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        f"sub/a.txt:2: home-path: {PERSON}",
        f"sub/a.txt:3: email: jane{AT}uni.edu",
        "2 findings",
    ]


def test_missing_denylist_warns_by_default_and_fails_when_required(tmp_path):
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "a.txt").write_text("fine\n")
    missing = tmp_path / "no-such-file"
    result = run_sh("--dir", str(tree), denylist=missing)
    assert result.returncode == 0
    assert "warning: denylist not found" in result.stderr
    assert "denylist: not found" in result.stdout
    required = run_sh("--dir", str(tree), "--require-denylist", denylist=missing)
    assert required.returncode == 2
    assert f"denylist not found: {missing} (set DISCJOCKEY_PUBLIC_DENYLIST)" in required.stderr


def test_an_empty_denylist_passes_unless_it_is_required(tmp_path, empty_denylist):
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "a.txt").write_text("fine\n")
    assert run_sh("--dir", str(tree), denylist=empty_denylist).returncode == 0
    required = run_sh("--dir", str(tree), "--require-denylist", denylist=empty_denylist)
    assert required.returncode == 2
    assert f"denylist has no entries: {empty_denylist}" in required.stderr
    blank = tmp_path / "blank"
    blank.write_text("\n  \n")  # an empty secret written to a file is a newline
    assert run_sh("--dir", str(tree), "--require-denylist", denylist=blank).returncode == 2


@pytest.mark.parametrize("required", [False, True])
def test_a_denylist_that_cannot_be_read_is_exit_2_with_one_line(tmp_path, required):
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "a.txt").write_text("fine\n")
    folder = tmp_path / "a-folder"
    folder.mkdir()
    args = ["--dir", str(tree)] + (["--require-denylist"] if required else [])
    result = run_sh(*args, denylist=folder)
    assert result.returncode == 2
    assert result.stderr.strip() == f"denylist cannot be read: {folder}"


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads every file")
def test_a_denylist_nobody_may_read_is_exit_2(tmp_path):
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "a.txt").write_text("fine\n")
    locked = tmp_path / "locked"
    locked.write_text("word\n")
    locked.chmod(0)
    result = run_sh("--dir", str(tree), denylist=locked)
    assert result.returncode == 2
    assert result.stderr.strip() == f"denylist cannot be read: {locked}"


def test_usage_errors_exit_2(tmp_path, empty_denylist):
    assert run_sh("--bogus", denylist=empty_denylist).returncode == 2
    assert run_sh("--dir", str(tmp_path / "nope"), denylist=empty_denylist).returncode == 2


def test_repo_mode_skips_pre_public_and_dir_mode_does_not(tmp_path, empty_denylist):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    for name in ("check_public.sh", "check_public.py"):
        shutil.copy2(SCRIPTS / name, repo / "scripts" / name)
    (repo / "docs" / "archive" / "pre-public").mkdir(parents=True)
    (repo / "docs" / "archive" / "pre-public" / "old.md").write_text(f"{PERSON}/Music\n")
    (repo / "docs" / "note.md").write_text(f"{HOME}you/Music\n")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "docs", "scripts"], cwd=repo, check=True)
    clean = run_sh(denylist=empty_denylist, script=repo / "scripts" / "check_public.sh")
    assert clean.returncode == 0, clean.stdout
    assert "(3 files" in clean.stdout  # the two scripts and docs/note.md, not old.md
    everything = run_sh("--dir", str(repo), denylist=empty_denylist, script=repo / "scripts" / "check_public.sh")
    assert everything.returncode == 1
    assert "docs/archive/pre-public/old.md:1: home-path" in everything.stdout


def test_repo_mode_ignores_untracked_files(tmp_path, empty_denylist):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    for name in ("check_public.sh", "check_public.py"):
        shutil.copy2(SCRIPTS / name, repo / "scripts" / name)
    (repo / "untracked.txt").write_text(f"{PERSON}/Music\n")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "scripts"], cwd=repo, check=True)
    assert run_sh(denylist=empty_denylist, script=repo / "scripts" / "check_public.sh").returncode == 0


def test_symlink_target_text_is_scanned_in_dir_mode_and_never_followed(tmp_path, empty_denylist):
    tree = tmp_path / "tree"
    tree.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "big.txt").write_text(f"{PERSON}/in-the-target-file\n")  # must not be read through the link
    (tree / "link").symlink_to(PERSON + "/Music")  # dangling, points at a made-up home
    (tree / "folder-link").symlink_to(outside, target_is_directory=True)
    result = run_sh("--dir", str(tree), denylist=empty_denylist)
    assert result.returncode == 1
    assert result.stdout.splitlines() == [f"link:1: home-path: {PERSON}", "1 findings"]


def test_symlink_target_text_is_scanned_in_repo_mode(tmp_path, empty_denylist):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    for name in ("check_public.sh", "check_public.py"):
        shutil.copy2(SCRIPTS / name, repo / "scripts" / name)
    (repo / "link").symlink_to(PERSON + "/Music")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "scripts", "link"], cwd=repo, check=True)
    result = run_sh(denylist=empty_denylist, script=repo / "scripts" / "check_public.sh")
    assert result.returncode == 1
    assert f"link:1: home-path: {PERSON}" in result.stdout


def test_tracked_file_missing_on_disk_is_an_error_not_clean(tmp_path, empty_denylist):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    for name in ("check_public.sh", "check_public.py"):
        shutil.copy2(SCRIPTS / name, repo / "scripts" / name)
    (repo / "gone.txt").write_text("x\n")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "scripts", "gone.txt"], cwd=repo, check=True)
    (repo / "gone.txt").unlink()
    result = run_sh(denylist=empty_denylist, script=repo / "scripts" / "check_public.sh")
    assert result.returncode == 2
    assert "gone.txt: tracked file is missing on disk" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read everything")
def test_unreadable_file_is_an_error_not_a_traceback(tmp_path, empty_denylist):
    tree = tmp_path / "tree"
    tree.mkdir()
    secret = tree / "locked.txt"
    secret.write_text("x\n")
    secret.chmod(0)
    try:
        result = run_sh("--dir", str(tree), denylist=empty_denylist)
    finally:
        secret.chmod(0o600)
    assert result.returncode == 2
    assert "locked.txt: cannot read" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read everything")
def test_unreadable_folder_is_an_error_not_a_skip(tmp_path, empty_denylist):
    tree = tmp_path / "tree"
    locked = tree / "locked"
    locked.mkdir(parents=True)
    (locked / "inside.txt").write_text("x\n")
    locked.chmod(0)
    try:
        result = run_sh("--dir", str(tree), denylist=empty_denylist)
    finally:
        locked.chmod(0o700)
    assert result.returncode == 2
    assert "locked: cannot read the folder" in result.stderr
    assert "1 file or folder could not be read" in result.stderr


def test_the_script_itself_holds_no_personal_word():
    """The scripts are tracked too: they must pass their own check (the handle appears only in the repo-url rule)."""
    own = [(p.name, p.read_bytes()) for p in (SCRIPTS / "check_public.sh", SCRIPTS / "check_public.py")]
    assert cp.scan(own, []) == []


def test_the_real_repo_is_clean(empty_denylist):
    result = run_sh(denylist=empty_denylist)
    assert result.returncode == 0, result.stdout[-2000:]
