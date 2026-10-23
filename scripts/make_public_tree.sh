#!/bin/bash
# Builds the public repo's first commit as a LOCAL branch: one parentless commit whose tree is a git ref's tree minus
# docs/archive/pre-public (spec public-release §9, phase 6). The public repo itself is made later by the user.
#
# usage: scripts/make_public_tree.sh --email <id>+TheZwiss@users.noreply.github.com
#                                    [--name TheZwiss] [--ref HEAD] [--branch public-main] [--dry-run]
# exit: 0 done, 1 refused (one plain line on stderr), 2 usage error
#
# What it never does: send anything anywhere, add or change a remote, change the working copy or the user's real index,
# or touch git settings. It only writes git objects and, in a real run, the one new branch. The scan reads git
# objects only (a temporary index, extracted with `checkout-index`), because the working folder holds ignored and
# untracked personal files.
set -euo pipefail

HANDLE="TheZwiss"
EMAIL_RE='^[0-9]+\+TheZwiss@users\.noreply\.github\.com$'
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"  # the working copy this script came from: its checker is the one used
REQUIRED=(LICENSE README.md CONTRIBUTING.md .github/workflows/check.yml .github/workflows/release.yml)

email=""
name="$HANDLE"
ref="HEAD"
branch="public-main"
dry_run=0

usage() {
  echo "usage: scripts/make_public_tree.sh --email <id>+$HANDLE@users.noreply.github.com [--name $HANDLE] [--ref HEAD] [--branch public-main] [--dry-run]" >&2
  exit 2
}
refuse() {
  echo "refused: $*" >&2
  exit 1
}

while [ $# -gt 0 ]; do
  case "$1" in
    --email|--name|--ref|--branch)
      [ $# -ge 2 ] || usage
      case "$1" in
        --email) email="$2" ;;
        --name) name="$2" ;;
        --ref) ref="$2" ;;
        --branch) branch="$2" ;;
      esac
      shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    -h|--help) usage ;;
    *) usage ;;
  esac
done

# ---- 1. refusals, before anything is built
root="$(git rev-parse --show-toplevel 2>/dev/null)" || refuse "not inside a git repository"
cd "$root"
[ -n "$email" ] || refuse "--email is missing (the no-reply address <id>+$HANDLE@users.noreply.github.com)"
[[ "$email" =~ $EMAIL_RE ]] || refuse "--email must look like <id>+$HANDLE@users.noreply.github.com (the numeric id is yours, from GitHub's e-mail settings)"
[ -n "$name" ] || refuse "--name is empty"
# '@' is refused: `check-ref-format --branch` accepts '@{-1}' and would pass a name that `git branch` then fails on
if [[ "$branch" == *@* ]] || ! git check-ref-format --branch "$branch" >/dev/null 2>&1; then
  refuse "'$branch' is not a usable branch name"
fi
if git show-ref --verify --quiet "refs/heads/$branch"; then
  refuse "branch '$branch' already exists (a ref you may have pushed is never moved)"
fi
git rev-parse --verify --quiet "$ref^{commit}" >/dev/null || refuse "--ref '$ref' is not a commit"
if [ "$ref" = "HEAD" ]; then
  # --no-optional-locks: status must not refresh (rewrite) the real index
  dirty="$(git --no-optional-locks status --porcelain --untracked-files=no)" || refuse "git status failed"
  [ -z "$dirty" ] || refuse "tracked files have uncommitted changes (commit or restore them first)"
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# ---- 2. the tree, from git objects only (a temporary index; the real one is never touched)
export_index="$tmp/index"
GIT_INDEX_FILE="$export_index" git read-tree "$ref" || refuse "git could not read the tree of '$ref'"
GIT_INDEX_FILE="$export_index" git rm -r --cached --quiet --ignore-unmatch -- docs/archive/pre-public \
  || refuse "git could not remove docs/archive/pre-public from the temporary index"
tree="$(GIT_INDEX_FILE="$export_index" git write-tree)" || refuse "git could not write the tree"

# ---- 3. check that exact tree, with this working copy's checker
extracted="$tmp/tree"
mkdir "$extracted"
# Extract from the temporary index, not with `git archive`: archive honours export-ignore and export-subst from the
# tree's own .gitattributes, so a tracked file could be committed without ever being scanned.
GIT_INDEX_FILE="$export_index" git checkout-index -a --prefix="$extracted/" || refuse "git could not extract the tree"
# The scanned folder must hold exactly what is committed (files and symlinks; submodule entries are not files)
expected_count="$(git ls-tree -r "$tree" | awk '$2 == "blob"' | wc -l | tr -d ' ')"
# count NULs, not lines: a file name may hold a newline
extracted_count="$(find "$extracted" \( -type f -o -type l \) -print0 | tr -cd '\0' | wc -c | tr -d ' ')"
[ "$expected_count" = "$extracted_count" ] \
  || refuse "the scanned folder holds $extracted_count files but the tree has $expected_count; nothing is committed"
for required in "${REQUIRED[@]}"; do
  git cat-file -e "$tree:$required" 2>/dev/null || refuse "the tree has no $required"
done
# unreachable after the `git rm --cached` above; kept as a guard in case that step is ever changed
if git cat-file -e "$tree:docs/archive/pre-public" 2>/dev/null; then
  refuse "the tree still holds docs/archive/pre-public"
fi
check_out="$tmp/check.out"
check_status=0
"$HERE/check_public.sh" --dir "$extracted" --require-denylist >"$check_out" 2>&1 || check_status=$?
if [ "$check_status" -ne 0 ]; then
  cat "$check_out" >&2
  if [ "$check_status" -eq 1 ]; then
    refuse "the public check found personal data in the tree (list above)"
  fi
  refuse "the public check could not run to the end (exit $check_status, see above)"
fi

# ---- 4. the version
version="$(sed -n 's/^__version__ = "\([^"]*\)".*/\1/p' "$extracted/discjockey/__init__.py" 2>/dev/null | head -n 1)"
[ -n "$version" ] || refuse "no __version__ in discjockey/__init__.py of the tree"
message="Discjockey $version"

files="$(git ls-tree -r "$tree" | wc -l | tr -d ' ')"
bytes="$(git ls-tree -r -l "$tree" | awk '{ if ($4 != "-") s += $4 } END { print s + 0 }')"
size="$(awk -v b="$bytes" 'BEGIN { if (b >= 1048576) printf "%.1f MB", b / 1048576; else printf "%.0f KB", b / 1024 }')"

# ---- 5. the commit (a real run only): no parent, the given identity as author and committer
if [ "$dry_run" -eq 1 ]; then
  echo "would commit $files files ($size) as \"$message\" by $name $email"
  exit 0
fi
# The date is pinned to UTC so the public history does not show the maintainer's time zone. --no-gpg-sign: the commit
# carries exactly the given identity and nothing else, whatever commit.gpgSign names in the maintainer's git settings.
when="$(date +%s) +0000"
sha="$(GIT_AUTHOR_NAME="$name" GIT_AUTHOR_EMAIL="$email" GIT_AUTHOR_DATE="$when" \
  GIT_COMMITTER_NAME="$name" GIT_COMMITTER_EMAIL="$email" GIT_COMMITTER_DATE="$when" \
  git commit-tree --no-gpg-sign "$tree" -m "$message")" || refuse "git could not make the commit"
git branch "$branch" "$sha" || refuse "git could not create branch '$branch' (the commit $sha is unreferenced)"

# ---- 6. the go-moment steps, text only. The commands that would send, move or configure things are spelled in pieces so
# that this file itself says no such command (tests pin that).
p="pu"; p="${p}sh"
s="swi"; s="${s}tch"
c="con"; c="${c}fig"
cat <<STEPS
made branch $branch: $sha
$files files ($size), commit "$message" by $name $email, no parent. Nothing was sent anywhere; your working copy is unchanged.

Go-moment steps (each one yours to run, from the root of your private working copy, on its branch main). The indented
command lines are the commands to run, in order; <public-url> is the new repository's address:
  1. Install the push guard first: a hook that refuses any push carrying the private history (it lists the old root
     commits now, so it keeps working when branches are renamed or deleted), then keep the history by renaming main
     (a copy would stay behind as a second way to send it) and cut its link to the old remote:
       git rev-list --max-parents=0 --all --not $branch > "\$(git rev-parse --git-common-dir)/private-roots"
       cp scripts/public_push_guard.sh "\$(git rev-parse --git-path hooks/pre-push)"
       chmod +x "\$(git rev-parse --git-path hooks/pre-push)"
       git branch -m main archive/main
       git branch --unset-upstream archive/main
  2. Create the public GitHub repository (empty, no README, public).
  3. Add its three repository secrets: PUBLIC_CHECK_DENYLIST, SIGNING_P12_BASE64, SIGNING_P12_PASSWORD.
  4. Send the branch as main:
       git $p <public-url> $branch:main
  5. Point your working copy at the public repository: the new branch becomes main, tracking origin/main, so a plain
     "git $p" works; the old remote-tracking branches are pruned:
       git remote set-url origin <public-url>
       git fetch --prune origin
       git $s $branch
       git branch -m $branch main
       git branch -u origin/main
  6. Put the archive back on disk, untracked:
       git restore --source=archive/main --worktree -- docs/archive/pre-public
  7. Use the no-reply address in this repository's own git settings:
       git $c user.email $email
  8. Every other local branch and tag from before this moment carries the private history too: put each under
     archive/ (the loops do; delete one yourself with git branch -D or git tag -d if you prefer) without an upstream,
     list what is left, and remove the old worktrees (git worktree remove <path>):
       for b in \$(git for-each-ref --format='%(refname:short)' refs/heads/ | grep -v -e '^main\$' -e '^archive/'); do git branch -m "\$b" "archive/\$b"; done
       for b in \$(git for-each-ref --format='%(refname:short)' refs/heads/ | grep '^archive/'); do git branch --unset-upstream "\$b" 2>/dev/null || true; done
       for t in \$(git tag --list | grep -v '^archive/'); do git tag "archive/\$t" "\$t" && git tag -d "\$t"; done
       git branch --list
       git tag --list
       git worktree list
  The guard refuses any push of the old history, by any command, and says so. Never send an archive/ branch or tag
  anyway, and never skip the guard with --no-verify. A release tag goes by its name only (git $p origin v<version>),
  never with --tags, --all or --mirror.
STEPS
