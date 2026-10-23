"""Every `docs/archive/...` path cited in a tracked text file resolves (spec public-release §9).

The archive from before the public repo lives in `docs/archive/pre-public/`: tracked in the private repo, gitignored in
the public one, so a clone of the public repo lacks it. A citation under it may therefore point at nothing when the
folder is absent. The archive folder itself (`docs/archive/`) names where finished plans go, not a file: the public
repo has none until its first plan is archived, so it may be absent too. Every other citation must name a file or
folder that exists. The archived files themselves are
history and are not rewritten, so their own citations are not checked; nor are the tests, which build scratch repos
with made-up archive paths."""
import re
import subprocess
from pathlib import Path

import pytest

from discjockey import REPO

ARCHIVE = "docs/archive/"
PRE_PUBLIC = "docs/archive/pre-public"
NOT_CHECKED = (PRE_PUBLIC + "/", "tests/")
CITATION = re.compile(r"docs/archive/[A-Za-z0-9._/-]*")


def cited_archive_paths(text: str) -> list[str]:
    """The `docs/archive/...` paths in a text, without the sentence punctuation that may follow them."""
    return [m.group(0).rstrip(".,;:") for m in CITATION.finditer(text)]


def unresolved_citations(root: Path, files: list[str]) -> list[str]:
    """`<file>: <citation>` for each cited archive path under `root` that names nothing on disk."""
    pre_public_present = (root / PRE_PUBLIC).is_dir()
    problems = []
    for rel in files:
        if rel.startswith(NOT_CHECKED):
            continue
        data = (root / rel).read_bytes() if (root / rel).is_file() else b""
        if b"\0" in data[:8192]:
            continue
        for cited in cited_archive_paths(data.decode("utf-8", errors="replace")):
            if (root / cited).exists() or cited.rstrip("/") + "/" == ARCHIVE:
                continue
            if (cited == PRE_PUBLIC or cited.startswith(PRE_PUBLIC + "/")) and not pre_public_present:
                continue
            problems.append(f"{rel}: {cited}")
    return problems


def _tracked_files(root: Path) -> list[str]:
    listing = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True).stdout
    return [p for p in listing.decode("utf-8").split("\0") if p]


def test_every_archive_citation_in_the_repo_resolves():
    assert unresolved_citations(REPO, _tracked_files(REPO)) == []


def test_the_pre_public_archive_is_where_the_citations_say():
    if not (REPO / PRE_PUBLIC).is_dir():
        pytest.skip("a clone of the public repo: the archive from before it is on the maintainer's disk only")
    assert (REPO / PRE_PUBLIC / "2026-10-15-hub-design.md").is_file()


def test_nothing_from_before_the_public_repo_sits_outside_pre_public():
    assert not any((REPO / ARCHIVE).glob("2026-10-1*.md")), "the archive from before the public repo moved to pre-public/"


def test_citations_are_found_without_trailing_punctuation():
    text = "See `docs/archive/a-plan.md`. Also docs/archive/pre-public/b.md, and docs/archive/."
    assert cited_archive_paths(text) == ["docs/archive/a-plan.md", "docs/archive/pre-public/b.md", "docs/archive/"]


def test_a_missing_archive_file_is_reported(tmp_path):
    (tmp_path / "docs/archive").mkdir(parents=True)
    (tmp_path / "docs/archive/real.md").write_text("x")
    (tmp_path / "README.md").write_text("docs/archive/real.md and docs/archive/gone.md\n")
    assert unresolved_citations(tmp_path, ["README.md"]) == ["README.md: docs/archive/gone.md"]


def test_pre_public_citations_may_point_at_nothing_only_when_the_folder_is_absent(tmp_path):
    (tmp_path / "docs/archive").mkdir(parents=True)
    (tmp_path / "CLAUDE.md").write_text("spec: docs/archive/pre-public/old-design.md\n")
    assert unresolved_citations(tmp_path, ["CLAUDE.md"]) == []  # the public clone: no pre-public folder
    (tmp_path / PRE_PUBLIC).mkdir()
    assert unresolved_citations(tmp_path, ["CLAUDE.md"]) == ["CLAUDE.md: docs/archive/pre-public/old-design.md"]


def test_the_archive_folder_itself_may_be_absent(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("finished plans go into docs/archive/ and docs/archive\n")
    assert unresolved_citations(tmp_path, ["CLAUDE.md"]) == []  # the public repo before its first archived plan
    (tmp_path / "README.md").write_text("see docs/archive/gone.md and docs/archive/sub/\n")
    assert unresolved_citations(tmp_path, ["README.md"]) == ["README.md: docs/archive/gone.md",
                                                             "README.md: docs/archive/sub/"]


def test_the_archived_files_and_the_tests_are_not_checked(tmp_path):
    (tmp_path / PRE_PUBLIC).mkdir(parents=True)
    (tmp_path / PRE_PUBLIC / "plan.md").write_text("moved from docs/archive/plan.md\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_x.py").write_text("FIXTURE = 'docs/archive/pre-public/made-up.md'\n")
    assert unresolved_citations(tmp_path, [f"{PRE_PUBLIC}/plan.md", "tests/test_x.py"]) == []
