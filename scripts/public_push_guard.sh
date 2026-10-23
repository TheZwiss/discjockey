#!/bin/sh
# Git pre-push hook for the maintainer's checkout after the go-moment (docs/issues.md, issue 22): refuses any push that
# would send a commit with the private history's root commit(s) as an ancestor, whatever the command (`git push --all`,
# `--mirror`, `--tags`, `-u origin archive/main`, a bare sha). The roots are written once, at install time, into
# `private-roots` in the repository's common git folder (scripts/make_public_tree.sh prints the commands), so the guard
# keeps working after the archive/ branches are renamed or deleted. Deletions and pushes of public commits go through.
# If the roots file is missing or empty the guard refuses everything: a leak cannot be taken back.
# It also refuses a push whose new commits (the ones the remote does not have) carry a denylisted value in the author
# or committer name or e-mail or in the message. The denylist is the one scripts/check_public.sh reads
# ($DISCJOCKEY_PUBLIC_DENYLIST, else ~/.discjockey-public-denylist), matched the same way: one entry per line, comments
# and blank lines dropped, case-insensitive, a word boundary at each end that is a word character. The refusal never
# prints the value. A contributor has no denylist: the guard warns on stderr and skips only this check.
# It stops a slip, not a person: `git push --no-verify` skips every hook; never use it here.
zero_re='^0*$'
common="$(git rev-parse --git-common-dir)" || exit 1
roots_file="$common/private-roots"

refuse() {
  echo "refused: $1" >&2
  echo "This checkout's old history is private and must never be sent anywhere (docs/issues.md, issue 22)." >&2
  exit 1
}

# The commit-identity check. Reads `git log` records on stdin (\x1f between fields, \x1e after a record), prints the
# short sha of each commit holding an entry. Exit: 0 clean, 7 something found, anything else (1: an error): unknown.
# Keep the matching in step with load_denylist / _denylist_pattern in scripts/check_public.py.
check_py='
import re, sys
entries = []
with open(sys.argv[1], encoding="utf-8", errors="replace") as f:
    for raw in f.read().splitlines():
        entry = raw.strip()
        if entry and not entry.startswith("#"):
            entries.append(entry)
pats = [re.compile((r"(?<!\w)" if re.match(r"\w", e) else "") + re.escape(e) + (r"(?!\w)" if re.search(r"\w$", e) else ""),
                   re.IGNORECASE) for e in entries]
found = False
for record in sys.stdin.buffer.read().decode("utf-8", errors="replace").split("\x1e"):
    sha, _, rest = record.strip("\n").partition("\x1f")
    if sha and any(p.search(rest) for p in pats):
        print(sha[:7])
        found = True
sys.exit(7 if found else 0)
'
denylist="${DISCJOCKEY_PUBLIC_DENYLIST:-$HOME/.discjockey-public-denylist}"
case "$denylist" in "~"|"~/"*) denylist="$HOME${denylist#"~"}" ;; esac
check_names=1
if [ ! -e "$denylist" ]; then
  check_names=0
  echo "warning: denylist not found: $denylist (set DISCJOCKEY_PUBLIC_DENYLIST); commit names, e-mails and messages are not checked" >&2
fi

[ -s "$roots_file" ] || refuse "the guard has no list of private root commits ($roots_file is missing or empty)"

remote_name="${1:-}"
while read -r local_ref local_sha _remote_ref remote_sha; do
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
  [ "$check_names" -eq 1 ] || continue
  # only the commits the remote does not have: not reachable from any remote-tracking branch of this remote, nor from
  # the remote's own tip of this ref when that is known here
  exclude="--remotes=$remote_name"
  if ! echo "$remote_sha" | grep -Eq "$zero_re" && git rev-parse --verify --quiet "$remote_sha^{commit}" > /dev/null; then
    set -- "$commit" --not "$exclude" "$remote_sha"
  else
    set -- "$commit" --not "$exclude"
  fi
  new_commits="$(git rev-list "$@")" || refuse "$local_ref: git could not list the new commits; nothing was sent"
  bad="$(echo "$new_commits" | git log --stdin --no-walk=unsorted --format='%H%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1f%B%x1e' |
    python3 -I -c "$check_py" "$denylist")"
  status=$?
  if [ "$status" -eq 7 ]; then
    echo "refused: $local_ref carries a denylisted value (author/committer/message) in commit $(echo $bad); nothing was sent." >&2
    echo "Fix: set git config user.name and user.email in this repo, then git commit --amend --reset-author (older commits: rebase)." >&2
    exit 1
  elif [ "$status" -ne 0 ]; then  # anything else: the answer is unknown, so refuse too
    refuse "$local_ref: the denylist check could not run ($denylist, python3); nothing was sent"
  fi
done
exit 0
