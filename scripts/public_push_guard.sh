#!/bin/sh
# Git pre-push hook for the maintainer's checkout after the go-moment (docs/issues.md, issue 22): refuses any push that
# would send a commit with the private history's root commit(s) as an ancestor, whatever the command (`git push --all`,
# `--mirror`, `--tags`, `-u origin archive/main`, a bare sha). The roots are written once, at install time, into
# `private-roots` in the repository's common git folder (scripts/make_public_tree.sh prints the commands), so the guard
# keeps working after the archive/ branches are renamed or deleted. Deletions and pushes of public commits go through.
# If the roots file is missing or empty the guard refuses everything: a leak cannot be taken back.
# It stops a slip, not a person: `git push --no-verify` skips every hook; never use it here.
zero_re='^0*$'
common="$(git rev-parse --git-common-dir)" || exit 1
roots_file="$common/private-roots"

refuse() {
  echo "refused: $1" >&2
  echo "This checkout's old history is private and must never be sent anywhere (docs/issues.md, issue 22)." >&2
  exit 1
}

[ -s "$roots_file" ] || refuse "the guard has no list of private root commits ($roots_file is missing or empty)"

while read -r local_ref local_sha _remote_ref _remote_sha; do
  if echo "$local_sha" | grep -Eq "$zero_re"; then
    continue  # deleting a remote ref sends nothing
  fi
  commit="$(git rev-parse --verify --quiet "$local_sha^{commit}")" || continue  # a tag of a file or folder: no history
  while read -r root; do
    [ -n "$root" ] || continue
    git merge-base --is-ancestor "$root" "$commit"
    status=$?
    if [ "$status" -ne 1 ]; then  # 0: private ancestor; anything else: the answer is unknown, so refuse too
      refuse "$local_ref carries the private history (root ${root%"${root#???????}"}); nothing was sent"
    fi
  done < "$roots_file"
done
exit 0
