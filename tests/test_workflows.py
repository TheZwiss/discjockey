"""The CI workflows (spec public-release §7): pinned by their text, no YAML library. actionlint runs on both when it is
installed (the maintainer's Mac has it; a missing one skips that one test and says so)."""
import os
import re
import shutil
import subprocess
import textwrap

import pytest

from discjockey import REPO

WORKFLOWS = REPO / ".github" / "workflows"
CHECK = (WORKFLOWS / "check.yml").read_text()
RELEASE = (WORKFLOWS / "release.yml").read_text()
BOTH = {"check.yml": CHECK, "release.yml": RELEASE}


def code(text: str) -> str:
    """The file without its comment lines (a comment may name what the file must not do)."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def run_blocks(text: str) -> list[str]:
    """The text of every `run:` block, one-line or `|` style."""
    blocks, lines = [], text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)(?:- )?run:\s*(.*)$", line)
        if not m:
            continue
        indent, rest = len(m.group(1)), m.group(2)
        if rest and rest not in ("|", ">", "|-", ">-"):
            blocks.append(rest)
            continue
        body = []
        for nxt in lines[i + 1:]:
            if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= indent + 1 and not nxt.startswith(" " * (indent + 2)):
                break
            body.append(nxt)
        blocks.append("\n".join(body))
    return blocks


@pytest.mark.skipif(shutil.which("actionlint") is None, reason="actionlint is not installed (brew install actionlint)")
def test_actionlint_accepts_both_workflows():
    r = subprocess.run(["actionlint", *map(str, sorted(WORKFLOWS.glob("*.yml")))], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_there_are_exactly_these_two_workflows():
    assert sorted(p.name for p in WORKFLOWS.iterdir()) == ["check.yml", "release.yml"]
    assert CHECK.startswith("# ") and re.search(r"^name: check$", CHECK, re.M)
    assert re.search(r"^name: release$", RELEASE, re.M)


def test_release_runs_only_for_v_tags():
    on = RELEASE[RELEASE.index("\non:"):RELEASE.index("\npermissions:")]
    assert re.sub(r"\s+", " ", on).strip() == "on: push: tags: ['v*']"
    assert "workflow_dispatch" not in code(RELEASE)


def test_check_runs_on_every_branch_push_and_pull_request_but_not_on_tags():
    on = CHECK[CHECK.index("\non:"):CHECK.index("\npermissions:")]
    assert re.sub(r"\s+", " ", on).strip() == "on: push: branches: ['**'] pull_request:"
    assert "cancel-in-progress: true" in CHECK and "group: check-${{ github.ref }}" in CHECK


def test_release_never_cancels_and_is_serialised_per_ref():
    assert "group: release-${{ github.ref }}" in RELEASE and "cancel-in-progress: false" in RELEASE


def test_write_permission_is_only_in_the_release_workflow():
    assert re.search(r"^permissions:\n  contents: read$", CHECK, re.M) and "write" not in code(CHECK)
    assert re.search(r"^permissions:\n  contents: write$", RELEASE, re.M)
    assert len(re.findall(r"\bwrite\b", code(RELEASE))) == 1


@pytest.mark.parametrize("name", BOTH)
def test_both_run_on_macos_15_in_the_public_repository_only(name):
    text = BOTH[name]
    assert re.search(r"^    runs-on: macos-15$", text, re.M)
    assert re.search(r"^    if: github\.repository == 'TheZwiss/discjockey'$", text, re.M)
    assert re.search(r"^    timeout-minutes: %d$" % (30 if name == "check.yml" else 60), text, re.M)


@pytest.mark.parametrize("name", BOTH)
def test_both_run_the_public_check_and_install_the_ui_packages_but_not_the_ui_checks(name):
    text = BOTH[name]
    assert "scripts/check_public.sh" in text and "npm ci" in text
    assert "uv sync --frozen" in text and "packaging/fetch_tools.py --out dist/tools --cache dist/cache" in text
    # svelte-check, vitest and the design rules run locally before a release (CONTRIBUTING.md), not on a runner
    assert "npm run verify" not in code(text) and "playwright" not in code(text)
    # the cached tools follow the pins, the ffmpeg build script and the code that names the cached build
    assert "hashFiles('packaging/tools.json', 'packaging/build_ffmpeg.sh', 'packaging/fetch_tools.py')" in text


def test_only_check_runs_the_python_tests():
    """The release job runs no tests: they run locally before the tag (CONTRIBUTING.md, Releasing)."""
    assert "pytest -q" in code(CHECK) and "pytest" not in code(RELEASE)


def test_only_the_release_builds_ffmpeg_fresh_and_says_why():
    """A cached ffmpeg build has no hash to check; the job that signs and ships must not trust it (check.yml may)."""
    fetch = "packaging/fetch_tools.py --out dist/tools --cache dist/cache"
    assert f"{fetch} --fresh-build" in code(RELEASE)
    assert "--fresh-build" not in CHECK
    assert "can't be checked against any hash" in RELEASE


def test_the_draft_carries_the_ffmpeg_source_it_was_built_from():
    """GPL-3.0 section 6: the hash-checked FFmpeg tarball goes up with the .dmg, named from tools.json's version."""
    body = code(RELEASE)
    assert "jq -r .ffmpeg.version packaging/tools.json" in body and "jq -r .ffmpeg.sha256 packaging/tools.json" in body
    assert 'ffmpeg_source="dist/ffmpeg-$ffmpeg_version.tar.xz"' in body
    assert 'shasum -a 256 -c -' in body
    assert 'gh release upload "$TAG" "$dmg" "$ffmpeg_source" --clobber' in body
    assert '--generate-notes "$dmg" "$ffmpeg_source"' in body
    assert not re.search(r"\d+\.\d+\.\d+\.tar\.xz", body)  # the version is not written down a second time


def test_check_compares_the_committed_ui_build_with_a_fresh_one():
    """The check build_app.sh does in its step 1, so a stale hub/static fails a push, not only a release."""
    body = code(CHECK)
    step = next(b for b in run_blocks(CHECK) if "diff -rq" in b)
    assert "npm run build" in step and '--outDir "$RUNNER_TEMP/ui"' in step  # into a temporary folder, never the tree
    assert 'diff -rq "$RUNNER_TEMP/ui" discjockey/hub/static' in step and "exit 1" in step
    assert "npm ci" in body.split("diff -rq")[0]


def test_each_workflow_points_at_its_twin_for_the_duplicated_steps():
    assert "release.yml repeats them" in CHECK and "Twin of the \"Public check\" step in release.yml" in CHECK
    assert "check.yml on purpose" in RELEASE and "Twin of the \"Public check\" step in check.yml" in RELEASE


def test_check_requires_the_denylist_exactly_when_the_secret_is_there():
    block = next(b for b in run_blocks(CHECK) if "check_public.sh" in b)
    assert re.search(r'if \[ -n "\$PUBLIC_CHECK_DENYLIST" \]', block)
    yes, no = block.split("else")
    assert "--require-denylist" in yes and "--require-denylist" not in no


def test_release_always_requires_the_denylist_and_fails_without_the_secret():
    block = next(b for b in run_blocks(RELEASE) if "check_public.sh" in b)
    assert "check_public.sh --require-denylist" in block
    assert re.search(r'if \[ -z "\$PUBLIC_CHECK_DENYLIST" \]', block) and "exit 1" in block


def test_the_version_gate_comes_first_and_before_the_build():
    assert RELEASE.index("Version gate") < RELEASE.index("check_public.sh") < RELEASE.index("REQUIRE_IDENTITY=1")
    assert RELEASE.index("Version gate") < RELEASE.index("REQUIRE_IDENTITY=1 scripts/build_app.sh")
    gate = next(b for b in run_blocks(RELEASE) if "does not match version" in b)
    assert '"v$version" != "$TAG"' in gate and "tag $TAG does not match version $version" in gate
    assert "discjockey/__init__.py" in gate and "TAG: ${{ github.ref_name }}" in RELEASE


def test_release_builds_signed_and_only_drafts():
    assert "REQUIRE_IDENTITY=1 scripts/build_app.sh" in RELEASE
    body = code(RELEASE)
    assert "--draft" in body and "--draft=false" not in body
    assert "gh release edit" not in body and "--latest" not in body and "--prerelease=false" not in body
    assert "--verify-tag" in body and "--generate-notes" in body and "--clobber" in body
    assert "already published; not replacing its .dmg" in body
    assert re.search(r"GH_TOKEN: \$\{\{ github\.token \}\}", body)


def test_the_signing_secrets_have_their_binding_names():
    assert "SIGNING_P12_BASE64: ${{ secrets.SIGNING_P12_BASE64 }}" in RELEASE
    assert "SIGNING_P12_PASSWORD: ${{ secrets.SIGNING_P12_PASSWORD }}" in RELEASE
    assert "PUBLIC_CHECK_DENYLIST: ${{ secrets.PUBLIC_CHECK_DENYLIST }}" in RELEASE
    assert "PUBLIC_CHECK_DENYLIST: ${{ secrets.PUBLIC_CHECK_DENYLIST }}" in CHECK
    assert 'DISCJOCKEY_SIGNING_DIR="$RUNNER_TEMP/signing" scripts/import_signing_identity.sh' in RELEASE
    assert '"$RUNNER_TEMP/release.p12"' in RELEASE


def test_the_keychain_and_key_are_removed_even_after_a_failure():
    tail = RELEASE[RELEASE.index("Remove the signing keychain"):]
    assert "if: always()" in tail and "security delete-keychain" in tail and "release.p12" in tail


@pytest.mark.parametrize("name", BOTH)
def test_a_secret_never_appears_inside_a_run_block(name):
    for block in run_blocks(BOTH[name]):
        assert "${{" not in block, block  # every expression goes through env: or with:


@pytest.mark.parametrize("name", BOTH)
def test_every_action_is_pinned_to_a_full_commit(name):
    uses = re.findall(r"^\s*(?:- )?uses:\s*(\S+)(.*)$", BOTH[name], re.M)
    assert len(uses) >= 4
    for ref, rest in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), ref
        assert re.fullmatch(r"\s+# v\d+\.\d+\.\d+", rest), f"{ref}: the version belongs in a comment"


@pytest.mark.parametrize("name", BOTH)
def test_no_trigger_runs_untrusted_code_with_secrets(name):
    assert "pull_request_target" not in code(BOTH[name])
    assert "workflow_run" not in code(BOTH[name])


@pytest.mark.parametrize("name", BOTH)
def test_the_checkout_leaves_no_token_on_disk(name):
    assert re.search(r"actions/checkout@[0-9a-f]{40} # v\S+\n\s+with:\n\s+persist-credentials: false", BOTH[name])


def test_the_draft_step_names_its_repository_itself():
    assert "GH_REPO: ${{ github.repository }}" in RELEASE


def test_the_denylist_and_the_p12_are_deleted_when_their_step_ends():
    for text in BOTH.values():
        block = next(b for b in run_blocks(text) if "check_public.sh" in b)
        assert "trap 'rm -f \"$RUNNER_TEMP/denylist.txt\"' EXIT" in block
    block = next(b for b in run_blocks(RELEASE) if "import_signing_identity.sh" in b)
    assert "trap 'rm -f \"$RUNNER_TEMP/release.p12\"' EXIT" in block


@pytest.mark.parametrize("tag, exits", [("v{version}", 0), ("v{version}.1", 1), ("{version}", 1), ("v9.9.9", 1)])
def test_the_version_gate_runs_as_written(tmp_path, tag, exits):
    """The gate's own script, run against a scratch copy of __init__.py with a given tag."""
    version = re.search(r'^__version__ = "(.*)"', (REPO / "discjockey" / "__init__.py").read_text(), re.M).group(1)
    gate = textwrap.dedent(next(b for b in run_blocks(RELEASE) if "does not match version" in b))
    (tmp_path / "discjockey").mkdir()
    shutil.copy(REPO / "discjockey" / "__init__.py", tmp_path / "discjockey" / "__init__.py")
    out = tmp_path / "out"
    tag = tag.format(version=version)
    r = subprocess.run(["bash", "-eo", "pipefail", "-c", gate], cwd=tmp_path, capture_output=True, text=True,
                       env={**os.environ, "TAG": tag, "GITHUB_OUTPUT": str(out)})
    assert r.returncode == exits, r.stdout + r.stderr
    if exits == 0:
        assert out.read_text() == f"version={version}\n"
    else:
        assert f"::error::tag {tag} does not match version {version}" in r.stdout and not out.exists()
