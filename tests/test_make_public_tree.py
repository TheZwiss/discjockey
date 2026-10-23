"""scripts/make_public_tree.sh: the public repo's first commit, built locally (phase 6). Each test runs the script
inside a scratch repo in tmp_path. Forbidden samples are built from pieces at runtime, so this file passes the check
itself; the names are made-up stand-ins."""
import os
import re
import shutil
import subprocess

import pytest

from discjockey import REPO

SCRIPTS = REPO / "scripts"
HOME = "/Us" + "ers/"
PERSON_PATH = HOME + "jane/Music"  # a made-up person's home path
HANDLE = "The" + "Zwiss"
EMAIL = f"12345+{HANDLE}@users.noreply.github.com"
SECRET_WORD = "Zebra" + "foo"  # the denylist word of these tests
ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "Dev", "GIT_AUTHOR_EMAIL": "dev@example.com",
    "GIT_COMMITTER_NAME": "Dev", "GIT_COMMITTER_EMAIL": "dev@example.com",
}


class Scratch:
    def __init__(self, path):
        self.path = path
        self.denylist = path.parent / "denylist.txt"
        self.denylist.write_text(SECRET_WORD + "\n")

    def git(self, *args, check=True, cwd=None):
        env = {**os.environ, **ENV}
        for name in ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE"):
            env.pop(name, None)
        return subprocess.run(["git", *args], cwd=cwd or self.path, env=env, capture_output=True, text=True,
                              check=check).stdout.strip()

    def run(self, *args, denylist="default", cwd=None):
        env = {**os.environ, **ENV}
        if denylist == "default":
            env["DISCJOCKEY_PUBLIC_DENYLIST"] = str(self.denylist)
        else:
            env["DISCJOCKEY_PUBLIC_DENYLIST"] = str(denylist)
        return subprocess.run(["bash", str(self.path / "scripts" / "make_public_tree.sh"), *args],
                              cwd=cwd or self.path, env=env, capture_output=True, text=True)

    def write(self, rel, text):
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def commit_all(self, message="more"):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def refs(self):
        return self.git("for-each-ref")

    def snapshot(self):
        index_mtime = (self.path / ".git" / "index").stat().st_mtime_ns  # before `status`, which may refresh the index
        return (self.git("rev-parse", "HEAD"), self.git("symbolic-ref", "HEAD"),
                self.git("--no-optional-locks", "status", "--porcelain"), index_mtime, self.git("branch", "--list"))


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    s = Scratch(root)
    s.git("init", "-q", "-b", "main")
    for rel in ("LICENSE", "README.md", "CONTRIBUTING.md", ".github/workflows/check.yml",
                ".github/workflows/release.yml"):
        s.write(rel, "text\n")
    s.write("discjockey/__init__.py", '"""x"""\n__version__ = "1.0.0"\n')
    s.write("docs/archive/pre-public/old.md", f"see {PERSON_PATH}\n")
    s.write(".gitignore", "ignored.txt\n")
    shutil.copytree(SCRIPTS, root / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    s.commit_all("first")
    s.write("untracked.txt", f"{PERSON_PATH}\n")  # untracked and ignored files hold forbidden text
    s.write("ignored.txt", f"{PERSON_PATH} {SECRET_WORD}\n")
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, env={**os.environ, **ENV})
    s.git("remote", "add", "origin", str(bare))
    s.bare = bare
    return s


def tree_files(s, ref):
    return set(s.git("ls-tree", "-r", "--name-only", ref).splitlines())


def test_real_run_makes_one_parentless_commit_with_the_given_identity(repo):
    r = repo.run("--email", EMAIL, "--name", "Jane Doe")
    assert r.returncode == 0, r.stderr
    sha = repo.git("rev-parse", "public-main")
    assert r.stdout.splitlines()[0].endswith(sha)
    assert repo.git("rev-list", "--parents", "-n1", "public-main") == sha  # no parent
    assert repo.git("rev-list", "--count", "public-main") == "1"
    assert repo.git("log", "-1", "--format=%an|%ae|%cn|%ce|%s", "public-main") == \
        f"Jane Doe|{EMAIL}|Jane Doe|{EMAIL}|Discjockey 1.0.0"
    expected = tree_files(repo, "HEAD") - {"docs/archive/pre-public/old.md"}
    assert tree_files(repo, "public-main") == expected
    assert not {"untracked.txt", "ignored.txt"} & tree_files(repo, "public-main")
    assert repo.git("rev-parse", "public-main:LICENSE") == repo.git("rev-parse", "HEAD:LICENSE")
    assert "go-moment" in r.stdout.lower() and "archive/main" in r.stdout and "PUBLIC_CHECK_DENYLIST" in r.stdout


def test_default_name_is_the_handle(repo):
    assert repo.run("--email", EMAIL).returncode == 0
    assert repo.git("log", "-1", "--format=%an|%cn", "public-main") == f"{HANDLE}|{HANDLE}"


def test_ref_other_than_head_and_custom_branch(repo):
    first = repo.git("rev-parse", "HEAD")
    repo.write("later.txt", "x\n")
    repo.commit_all()
    r = repo.run("--email", EMAIL, "--ref", first, "--branch", "other")
    assert r.returncode == 0, r.stderr
    assert "later.txt" not in tree_files(repo, "other")
    assert "public-main" not in repo.git("branch", "--list")


def test_the_source_checkout_and_origin_are_untouched(repo):
    before = repo.snapshot()
    remotes, config = repo.git("remote", "-v"), (repo.path / ".git" / "config").read_text()
    r = repo.run("--email", EMAIL)
    assert r.returncode == 0, r.stderr
    after = repo.snapshot()
    assert after[:4] == before[:4]  # same HEAD, branch, status and real index file
    names = lambda out: {line.lstrip("* ").strip() for line in out.splitlines()}  # noqa: E731
    assert names(after[4]) == names(before[4]) | {"public-main"}  # only the new branch is added
    assert (repo.path / "docs/archive/pre-public/old.md").exists()
    assert repo.git("for-each-ref", cwd=repo.bare) == ""  # nothing was pushed
    assert repo.git("remote", "-v") == remotes  # no remote added or changed
    assert (repo.path / ".git" / "config").read_text() == config  # no git setting changed


def test_dry_run_creates_no_ref_and_no_commit(repo):
    before_refs = repo.refs()
    before = repo.snapshot()
    r = repo.run("--email", EMAIL, "--dry-run")
    assert r.returncode == 0, r.stderr
    n = len(tree_files(repo, "HEAD")) - 1
    assert re.fullmatch(rf'would commit {n} files \(.+\) as "Discjockey 1\.0\.0" by {HANDLE} {re.escape(EMAIL)}',
                        r.stdout.strip()), r.stdout
    assert repo.refs() == before_refs
    assert repo.snapshot() == before


def refused(repo, *args, **kw):
    refs, snap = repo.refs(), repo.snapshot()
    r = repo.run(*args, **kw)
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert r.stderr.strip().splitlines()[-1].startswith("refused:")
    assert repo.refs() == refs and repo.snapshot() == snap
    assert "public-main" not in repo.git("branch", "--list")
    return r


def test_refuses_a_bad_email(repo):
    refused(repo, "--email", "me@example.com")
    refused(repo, "--email", f"{HANDLE}@users.noreply.github.com")  # no numeric id
    refused(repo, "--email", f"12345+Other@users.noreply.github.com")


def test_refuses_a_missing_email(repo):
    refused(repo)


def test_refuses_an_existing_branch(repo):
    repo.git("branch", "public-main")
    refs = repo.refs()
    r = repo.run("--email", EMAIL)
    assert r.returncode == 1 and "already exists" in r.stderr
    assert repo.refs() == refs


def test_refuses_uncommitted_changes_to_tracked_files(repo):
    repo.write("README.md", "changed\n")
    r = refused(repo, "--email", EMAIL)
    assert "uncommitted" in r.stderr


def test_refuses_outside_a_git_repo(tmp_path):
    script = tmp_path / "make_public_tree.sh"
    shutil.copy(SCRIPTS / "make_public_tree.sh", script)
    r = subprocess.run(["bash", str(script), "--email", EMAIL], cwd=tmp_path, capture_output=True, text=True,
                       env={**os.environ, **ENV, "GIT_CEILING_DIRECTORIES": str(tmp_path.parent)})
    assert r.returncode == 1 and "not inside a git repository" in r.stderr


def test_refuses_when_a_tracked_file_outside_the_archive_holds_personal_data(repo):
    repo.write("docs/notes.md", f"my folder {PERSON_PATH}\n")
    repo.commit_all()
    r = refused(repo, "--email", EMAIL)
    assert "docs/notes.md" in r.stderr and "home-path" in r.stderr


def test_refuses_on_a_denylist_word(repo):
    repo.write("docs/notes.md", f"for {SECRET_WORD}\n")
    repo.commit_all()
    refused(repo, "--email", EMAIL)


@pytest.mark.parametrize("missing", ["LICENSE", "README.md", "CONTRIBUTING.md", ".github/workflows/check.yml",
                                     ".github/workflows/release.yml"])
def test_refuses_a_tree_missing_a_required_file(repo, missing):
    repo.git("rm", "-q", missing)
    repo.git("commit", "-q", "-m", "drop")
    r = refused(repo, "--email", EMAIL)
    assert missing in r.stderr


def test_refuses_without_a_denylist_file(repo, tmp_path):
    r = refused(repo, "--email", EMAIL, denylist=tmp_path / "nowhere.txt")
    assert "denylist" in r.stderr


def test_refuses_a_file_hidden_from_git_archive_by_export_ignore(repo):
    repo.write("docs/hidden.md", f"my folder {PERSON_PATH}\n")
    repo.write(".gitattributes", "docs/hidden.md export-ignore\n")
    repo.commit_all()
    r = refused(repo, "--email", EMAIL)  # the scan sees every committed file, so the check fails
    assert "docs/hidden.md" in r.stderr and "home-path" in r.stderr


def test_a_file_name_with_a_newline_counts_once(repo):
    repo.write("docs/two\nlines.md", "text\n")
    repo.git("add", "docs")
    repo.git("commit", "-q", "-m", "newline")
    r = repo.run("--email", EMAIL)
    assert r.returncode == 0, r.stderr


def test_the_commit_date_is_utc_whatever_the_local_time_zone(repo):
    env = {**os.environ, **ENV, "TZ": "Pacific/Auckland", "DISCJOCKEY_PUBLIC_DENYLIST": str(repo.denylist)}
    r = subprocess.run(["bash", str(repo.path / "scripts" / "make_public_tree.sh"), "--email", EMAIL], cwd=repo.path,
                       env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    dates = repo.git("log", "-1", "--format=%ai|%ci", "public-main").split("|")
    assert all(d.endswith("+0000") for d in dates), dates


@pytest.mark.parametrize("branch", ["@{-1}", "a@b", "bad name", "x..y"])
def test_refuses_an_unusable_branch_name(repo, branch):
    refused(repo, "--email", EMAIL, "--branch", branch)


def test_unknown_option_is_a_usage_error(repo):
    assert repo.run("--email", EMAIL, "--bogus").returncode == 2
    assert repo.run("--email").returncode == 2


def test_the_script_never_sends_moves_or_configures():
    text = (SCRIPTS / "make_public_tree.sh").read_text()
    for pattern in (r"git push", r"\bgh ", r"remote add", r"checkout(?!-index)", r"switch", r"git reset", r"git config"):
        assert not re.search(pattern, text), pattern  # checkout-index only writes into a scratch folder
    code = text.split("cat <<STEPS")[0]  # the piecewise words ($p, $s, $c) may only appear in the printed text
    code = "\n".join(l for l in code.splitlines() if not re.match(r"[psc]=", l))  # the assignments themselves are fine
    assert not re.search(r"\$\{?[psc]\b", code)


def printed_commands(stdout):
    """The commands of the go-moment steps, exactly as the script prints them: the lines indented by seven spaces (the
    step text is indented by two or five)."""
    return [m.group(1) for line in stdout.splitlines() if (m := re.match(r" {7}(\S.*)$", line))]


def sh(repo, command, url):
    """Runs one printed command in the scratch repo. <public-url> is the only placeholder a command may hold."""
    command = command.replace("<public-url>", str(url))
    assert "<" not in command, command
    env = {**os.environ, **ENV}
    return subprocess.run(["bash", "-c", command], cwd=repo.path, env=env, capture_output=True, text=True)


def test_the_printed_go_moment_steps_leave_no_private_history_to_send(repo, tmp_path):
    """Replays the steps the script really prints against a scratch repo; both "remotes" are local bare repos (the
    old private one and the new public one), nothing touches a network."""
    s = repo
    s.write(".gitignore", "ignored.txt\ndocs/archive/pre-public/\n")  # as in the real repo
    s.git("add", ".gitignore")  # not -A: untracked.txt must stay untracked
    s.git("commit", "-q", "-m", "ignore the archive")
    # before the cutover: private history on main, tracking the old remote, plus another branch, a tag and a worktree
    s.git("push", "-q", "-u", "origin", "main")
    s.git("branch", "feature")
    s.git("push", "-q", "origin", "feature")
    s.git("tag", "old-tag")
    s.git("tag", "-a", "-m", "old note", "old-annotated")
    s.git("worktree", "add", "-q", str(tmp_path / "wt"), "-b", "wt-branch")
    old_sha = s.git("rev-parse", "HEAD")
    assert s.git("rev-parse", "--abbrev-ref", "main@{upstream}") == "origin/main"

    made = s.run("--email", EMAIL)
    assert made.returncode == 0, made.stderr
    commands = printed_commands(made.stdout)
    assert len(commands) >= 10, made.stdout
    # the printed text must never offer a way to send more than the one branch (checked on the printed lines)
    sends = [c for c in commands if re.match(r"git push\b", c)]
    assert sends == ["git push <public-url> public-main:main"], sends
    assert not re.search(r"--(tags|all|mirror)\b", "\n".join(sends))
    assert not any(c.startswith("$") for c in commands)

    public = tmp_path / "public.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(public)], check=True, env={**os.environ, **ENV})
    for command in commands:
        r = sh(s, command, public)
        assert r.returncode == 0, (command, r.stdout, r.stderr)

    # the public repo: one parentless commit on main, nothing else
    assert s.git("for-each-ref", "--format=%(refname)", cwd=public) == "refs/heads/main"
    assert s.git("rev-list", "--all", "--count", cwd=public) == "1"
    assert s.git("rev-list", "--parents", "-n1", "main", cwd=public).count(" ") == 0
    assert subprocess.run(["git", "cat-file", "-e", old_sha], cwd=public, capture_output=True).returncode != 0

    # the working copy: main is the public branch, a plain send goes to origin/main, the old history is only archive/*
    assert s.git("remote", "get-url", "origin") == str(public)
    assert s.git("symbolic-ref", "--short", "HEAD") == "main"
    assert s.git("rev-parse", "--abbrev-ref", "main@{upstream}") == "origin/main"
    assert s.git("rev-list", "--parents", "-n1", "main").count(" ") == 0
    branches = set(s.git("for-each-ref", "--format=%(refname:short)", "refs/heads").splitlines())
    assert branches == {"main", "archive/main", "archive/feature", "archive/wt-branch"}, branches
    assert s.git("config", "--get", "branch.archive/main.remote", check=False) == ""  # no upstream: cannot be sent
    remote_refs = set(s.git("for-each-ref", "--format=%(refname)", "refs/remotes").splitlines())
    assert remote_refs - {"refs/remotes/origin/HEAD"} == {"refs/remotes/origin/main"}, remote_refs  # origin/feature pruned
    assert s.git("rev-parse", "origin/main") == s.git("rev-parse", "main")
    assert s.git("config", "user.email") == EMAIL
    # the archive is back on disk, untracked and ignored
    assert (s.path / "docs/archive/pre-public/old.md").read_text() == f"see {PERSON_PATH}\n"
    assert s.git("ls-files", "docs/archive/pre-public") == ""
    assert s.git("check-ignore", "docs/archive/pre-public/old.md") != ""

    assert set(s.git("tag", "--list").splitlines()) == {"archive/old-tag", "archive/old-annotated"}  # moved, not left
    assert s.git("config", "--get-regexp", r"^branch\.archive/.*\.(remote|merge)$", check=False) == ""  # no upstreams

    # the guard: every way to send the old history is refused, and the public repo does not change
    s.git("tag", "late-tag", "archive/main")  # a tag made after the steps
    for args in (["--all"], ["--mirror"], ["--tags"], ["-u", "origin", "archive/main"], ["origin", "archive/feature"],
                 ["origin", "late-tag"], ["origin", old_sha + ":refs/heads/leak"]):
        r = subprocess.run(["git", "push", *args], cwd=s.path, env={**os.environ, **ENV}, capture_output=True, text=True)
        assert r.returncode != 0 and "private history" in r.stderr, (args, r.stdout, r.stderr)
        assert s.git("for-each-ref", "--format=%(refname) %(objectname)", cwd=public) == f"refs/heads/main {s.git('rev-parse', 'main')}", args
        assert s.git("rev-list", "--all", "--count", cwd=public) == "1", args
    s.git("tag", "-d", "late-tag")
    # without the roots file the guard refuses everything (a leak cannot be taken back)
    roots = s.path / ".git" / "private-roots"
    kept = roots.read_text()
    roots.unlink()
    r = subprocess.run(["git", "push"], cwd=s.path, env={**os.environ, **ENV}, capture_output=True, text=True)
    assert r.returncode != 0 and "no list of private root commits" in r.stderr
    roots.write_text(kept)

    # daily work: a plain `git push` goes to origin/main and still carries only public history
    s.write("later.txt", "x\n")
    s.git("add", "later.txt")
    s.git("commit", "-q", "-m", "later")
    pushed = subprocess.run(["git", "push", "-q"], cwd=s.path, env={**os.environ, **ENV}, capture_output=True, text=True)
    assert pushed.returncode == 0, pushed.stderr
    assert s.git("rev-parse", "main", cwd=public) == s.git("rev-parse", "main")
    assert s.git("rev-list", "--all", "--count", cwd=public) == "2"
    assert s.git("for-each-ref", "--format=%(refname)", cwd=public) == "refs/heads/main"


def test_the_public_commit_is_not_signed_whatever_the_git_settings_say(repo):
    repo.git("config", "commit.gpgsign", "true")
    repo.git("config", "gpg.program", "false")  # a signing attempt would fail the run
    r = repo.run("--email", EMAIL)
    assert r.returncode == 0, r.stderr
    assert "gpgsig" not in repo.git("cat-file", "-p", "public-main")


def test_issue_22_contributing_and_claude_md_say_what_the_script_prints(repo):
    """The printed go-moment commands, the issue's steps, CONTRIBUTING and CLAUDE.md must agree."""
    squash = lambda text: re.sub(r"\s+", " ", text)  # noqa: E731
    commands = printed_commands(repo.run("--email", EMAIL).stdout)
    issue = squash((REPO / "docs" / "issues.md").read_text())
    issue = issue[issue.index("## 22. Go public"):]
    for command in commands:
        if command.startswith(("for ", "git config")):  # a loop and an address the issue only describes
            continue
        assert command in issue, command
    assert "git push origin v1.0.0" in issue and "never `--tags`, `--all` or `--mirror`" in issue
    for name in ("CONTRIBUTING.md", "CLAUDE.md"):
        text = squash((REPO / name).read_text())
        assert re.search(r"git push origin v<version>|git push origin v1\.0\.1", text), name
        assert "`--tags`" in text and "`--all`" in text and "`--mirror`" in text, name
    assert "`archive/*` branches" in squash((REPO / "CLAUDE.md").read_text())
