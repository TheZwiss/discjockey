"""README.md (the user manual) and CONTRIBUTING.md (developer notes) as they go public (spec public-release §9):
every relative link and image resolves to a tracked file, every in-page anchor to a heading, the sections the
spec names exist, the download link is the public repo's, and every secret the workflows read is named in
CONTRIBUTING.md."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ("README.md", "CONTRIBUTING.md")
RELEASES = "https://github.com/TheZwiss/discjockey/releases/latest"

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


def test_readme_has_the_sections_the_spec_names():
    sections = _headings(_text("README.md"), 2)
    for heading in ("Download", "Requirements", 'Install and "Open Anyway"', "Updates", "One-time setup",
                    "Legal note", "Account risk", "Licence"):
        assert heading in sections, f"README.md has no '## {heading}'"
    # the legal note comes before the manual's details, so nobody downloads without having seen it
    assert sections.index("Legal note") < sections.index("One-time setup")


def test_readme_downloads_from_the_public_repo_only():
    text = _text("README.md")
    assert f"]({RELEASES})" in text
    repos = set(re.findall(r"github\.com/([\w.-]+/[\w.-]+)", text))
    assert repos == {"TheZwiss/discjockey"}, f"README.md points at other GitHub repos: {sorted(repos)}"


def test_readme_keeps_developer_commands_out():
    prose = FENCE.sub("", _text("README.md"))
    for word in ("bin/discjockey", "uv sync", "uv run", "npm ", "pytest"):
        assert word not in prose, f"README.md says '{word}': developer notes belong in CONTRIBUTING.md"


def test_contributing_names_every_secret_the_workflows_read():
    text = _text("CONTRIBUTING.md")
    secrets = set()
    for workflow in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        secrets |= set(re.findall(r"secrets\.([A-Z0-9_]+)", workflow.read_text(encoding="utf-8")))
    assert secrets, "the workflows read no secrets; the pattern is broken"
    for secret in sorted(secrets - {"GITHUB_TOKEN"}):
        assert f"`{secret}`" in text, f"CONTRIBUTING.md doesn't say what the secret {secret} holds"
