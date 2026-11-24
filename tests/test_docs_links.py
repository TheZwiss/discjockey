"""README.md (the landing page), docs/manual.md (the user manual), CONTRIBUTING.md (developer notes), AGENTS.md (the
guide for AI agents) and llms.txt (the index for LLM tools) as they go public (spec public-release §9):
every relative link and image resolves to a tracked file, every in-page anchor to a heading, the sections the
spec names exist, the download link is the public repo's, and every secret the workflows read is named in
CONTRIBUTING.md."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MANUAL = "docs/manual.md"
DOCS = ("README.md", MANUAL, "CONTRIBUTING.md", "AGENTS.md")
USER_DOCS = ("README.md", MANUAL)
RELEASES = "https://github.com/TheZwiss/discjockey/releases/latest"
BLOB = "https://github.com/TheZwiss/discjockey/blob/main/"

# [text](target) and ![alt](target); an optional "title" after the target is dropped. Code spans and fenced blocks
# are removed first, so a bracket inside an example is never read as a link.
LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
FENCE = re.compile(r"^```.*?^```", re.S | re.M)
CODE = re.compile(r"`[^`\n]*`")
IMG = re.compile(r"<img\b[^>]*\bsrc=\"([^\"]+)\"")


def _text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _prose(text: str) -> str:
    return CODE.sub("", FENCE.sub("", text))


def _tracked() -> set[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    return {p for p in out.decode("utf-8").split("\0") if p}


def _slug(heading: str) -> str:
    """GitHub's anchor for a heading: lower case, punctuation dropped (hyphens kept), spaces to hyphens."""
    words = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return words.replace(" ", "-")


def _anchors(text: str) -> set[str]:
    return {_slug(m.group(1)) for m in re.finditer(r"^#{1,6}\s+(.+?)\s*#*\s*$", FENCE.sub("", text), re.M)}


def _headings(text: str, level: int) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(rf"^{'#' * level}\s+(.+)$", FENCE.sub("", text), re.M)]


@pytest.mark.parametrize("name", DOCS)
def test_relative_links_and_images_resolve_to_tracked_files(name):
    tracked = _tracked()
    assert name in tracked
    base = (ROOT / name).parent
    targets = LINK.findall(_prose(_text(name))) + IMG.findall(_prose(_text(name)))
    assert targets, f"{name} has no links at all; the pattern is broken"
    for target in targets:
        if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
            continue
        path = target.split("#", 1)[0]
        rel = (base / path).resolve().relative_to(ROOT).as_posix()
        assert rel in tracked, f"{name} links to {target}, which is not a tracked file"


@pytest.mark.parametrize("name", DOCS)
def test_in_page_anchors_name_a_heading(name):
    text = _text(name)
    anchors = _anchors(text)
    for target in LINK.findall(_prose(text)):
        if target.startswith("#"):
            assert target[1:] in anchors, f"{name} links to {target}, but no heading has that anchor"


def test_slug_matches_github():
    assert _slug('Install and "Open Anyway"') == "install-and-open-anyway"
    assert _slug("Reports and not_lossless.md") == "reports-and-not_losslessmd"
    assert _slug("Where things live") == "where-things-live"


def test_manual_has_the_sections_the_spec_names():
    sections = _headings(_text(MANUAL), 2)
    for heading in ("Download", "Requirements", 'Install and "Open Anyway"', "Updates", "One-time setup",
                    "Legal note", "Account risk", "Licence"):
        assert heading in sections, f"{MANUAL} has no '## {heading}'"
    # the legal note comes before the manual's details, so nobody downloads without having seen it
    assert sections.index("Legal note") < sections.index("One-time setup")


@pytest.mark.parametrize("name", USER_DOCS)
def test_user_docs_download_from_the_public_repo_only(name):
    text = _text(name)
    assert f"]({RELEASES})" in text
    repos = set(re.findall(r"github\.com/([\w.-]+/[\w.-]+)", text))
    assert repos == {"TheZwiss/discjockey"}, f"{name} points at other GitHub repos: {sorted(repos)}"


@pytest.mark.parametrize("name", USER_DOCS)
def test_user_docs_keep_developer_commands_out(name):
    prose = FENCE.sub("", _text(name))
    for word in ("bin/discjockey", "uv sync", "uv run", "npm ", "pytest"):
        assert word not in prose, f"{name} says '{word}': developer notes belong in CONTRIBUTING.md"


def test_readme_is_a_short_landing_page_that_links_into_the_manual():
    text = _text("README.md")
    # 150 lines: the prose is about 100; the rest is the screenshot gallery's HTML table and the four Open Anyway
    # images, which the README shows itself so a visitor sees the app and the install steps without opening the manual
    assert len(text.splitlines()) <= 150, "README.md is the landing page; the details belong in docs/manual.md"
    anchors = _anchors(_text(MANUAL))
    deep = [t.split("#", 1)[1] for t in LINK.findall(_prose(text)) if t.startswith(f"{MANUAL}#")]
    assert deep, "README.md links to no section of the manual"
    for anchor in deep:
        assert anchor in anchors, f"README.md links to {MANUAL}#{anchor}, but the manual has no such heading"


@pytest.mark.parametrize("name", ("README.md", "llms.txt"))
def test_absolute_blob_links_point_at_a_tracked_file_and_heading(name):
    """llms.txt (and the README's AGENTS.md link) can't use relative links, so each absolute link into the public
    repo's main branch must name a file this tree tracks and, with an anchor, a heading in that file."""
    tracked = _tracked()
    links = [t for t in LINK.findall(_prose(_text(name))) if t.startswith(BLOB)]
    assert links, f"{name} has no links into the repo; the pattern is broken"
    for link in links:
        path, _, anchor = link[len(BLOB):].partition("#")
        assert path in tracked, f"{name} links to {link}, but {path} is not a tracked file"
        if anchor:
            assert anchor in _anchors(_text(path)), f"{name} links to {link}, but {path} has no heading with that anchor"


def test_contributing_names_every_secret_the_workflows_read():
    text = _text("CONTRIBUTING.md")
    secrets = set()
    for workflow in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        secrets |= set(re.findall(r"secrets\.([A-Z0-9_]+)", workflow.read_text(encoding="utf-8")))
    assert secrets, "the workflows read no secrets; the pattern is broken"
    for secret in sorted(secrets - {"GITHUB_TOKEN"}):
        assert f"`{secret}`" in text, f"CONTRIBUTING.md doesn't say what the secret {secret} holds"
