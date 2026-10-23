#!/bin/bash
# One-time: makes the self-signed "Discjockey Release" code-signing identity (spec public-release §6.3) in a keychain
# of its own, so every build signs with the same identity and macOS's grants survive updates.
# Never prompts: the keychain has a known password (kept next to it, mode 600), the certificate is not marked trusted
# (codesign doesn't need that), the login keychain and the keychain search list are left as they are.
# Refuses to replace an existing identity: a new one makes every user grant keychain and Full Disk Access again.
#
# usage: scripts/make_signing_identity.sh
#   DISCJOCKEY_SIGNING_DIR   where it goes (default ~/.discjockey-signing)
#   DISCJOCKEY_SIGNING_NAME  the certificate's name (default "Discjockey Release"; tests use another)
#   OPENSSL                  an OpenSSL 3 (default: the first openssl on PATH; macOS's LibreSSL lacks -legacy)
set -euo pipefail
DIR="${DISCJOCKEY_SIGNING_DIR:-$HOME/.discjockey-signing}"
NAME="${DISCJOCKEY_SIGNING_NAME:-Discjockey Release}"
KC="$DIR/discjockey-release.keychain-db"
OPENSSL="${OPENSSL:-$(command -v openssl || true)}"   # `|| true`: under set -e a failed lookup would exit silently

found=""
[ -e "$DIR/identity.sha1" ] && found="identity.sha1"
[ -e "$KC" ] && found="${found:+$found and }discjockey-release.keychain-db"
if [ -n "$found" ]; then
  echo "A signing identity already exists in $DIR ($found). Not replacing it (a new one makes every user grant access again)." >&2
  exit 1
fi
if [ -z "$OPENSSL" ] || ! "$OPENSSL" version | grep -q '^OpenSSL 3'; then
  echo "Needs OpenSSL 3 for -legacy PKCS#12 (brew install openssl@3, or set OPENSSL=<path>)." >&2
  exit 1
fi

# the user keychain search list, one path per line (paths may hold spaces; macOS's bash 3.2 has no mapfile)
unquote() {
  local line="$1"
  line="${line#"${line%%[![:space:]]*}"}"; line="${line#\"}"; line="${line%\"}"
  printf '%s' "$line"
}
read_list() {
  local line
  while IFS= read -r line; do
    line="$(unquote "$line")"
    if [ -n "$line" ]; then printf '%s\n' "$line"; fi
  done < <(security list-keychains -d user)
  return 0
}
saved="$(read_list)"
saved_default="$(unquote "$(security default-keychain -d user)")"

# put the search list and the default keychain back as they were (create-keychain leaves both alone on current macOS)
restore_state() {
  local line restore=()
  if [ "$(read_list)" != "$saved" ]; then
    while IFS= read -r line; do restore+=("$line"); done <<< "$saved"
    security list-keychains -d user -s "${restore[@]}"
  fi
  if [ -n "$saved_default" ] && [ "$(unquote "$(security default-keychain -d user)")" != "$saved_default" ]; then
    security default-keychain -d user -s "$saved_default"
  fi
}

WORK=""
DIR_CREATED=0
SETUP_DONE=0
cleanup() {
  local status=$?
  trap - EXIT
  if [ -n "$WORK" ]; then rm -rf "$WORK"; fi
  if [ "$SETUP_DONE" != 1 ]; then
    # a failed run must leave nothing behind that blocks the next one, and the keychain settings as they were
    if [ -e "$KC" ]; then security delete-keychain "$KC" >/dev/null 2>&1 || true; fi
    restore_state || echo "Could not restore the keychain search list; check: security list-keychains -d user" >&2
    if [ "$DIR_CREATED" = 1 ]; then
      rm -rf "$DIR"
      echo "Setup failed; nothing was kept. Run this again." >&2
    else
      echo "Setup failed. Delete the files this run made in $DIR (cert.pem, *.p12, *.pass, the keychain), then run it again." >&2
    fi
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 143' TERM HUP
trap 'exit 130' INT

if [ ! -e "$DIR" ]; then DIR_CREATED=1; fi
mkdir -p "$DIR"
chmod 700 "$DIR"
umask 077
WORK="$(mktemp -d)"

"$OPENSSL" rand -base64 24 | tr -d '\n' > "$DIR/keychain.pass"
"$OPENSSL" rand -base64 24 | tr -d '\n' > "$DIR/p12.pass"
cat > "$WORK/cs.cnf" <<EOF
[req]
distinguished_name=dn
x509_extensions=ext
prompt=no
[dn]
CN=$NAME
[ext]
basicConstraints=critical,CA:false
keyUsage=critical,digitalSignature
extendedKeyUsage=critical,codeSigning
subjectKeyIdentifier=hash
EOF
"$OPENSSL" req -x509 -newkey rsa:3072 -nodes -days 7300 -keyout "$WORK/key.pem" -out "$DIR/cert.pem" \
  -config "$WORK/cs.cnf" 2>/dev/null
"$OPENSSL" pkcs12 -export -legacy -inkey "$WORK/key.pem" -in "$DIR/cert.pem" -name "$NAME" \
  -out "$DIR/discjockey-release.p12" -passout "file:$DIR/p12.pass"

KCPASS="$(cat "$DIR/keychain.pass")"
security create-keychain -p "$KCPASS" "$KC"
security set-keychain-settings "$KC"   # no automatic lock
printf '%s\n' "$KCPASS" | security unlock-keychain "$KC"   # password on stdin, not in ps
security import "$DIR/discjockey-release.p12" -k "$KC" -P "$(cat "$DIR/p12.pass")" -T /usr/bin/codesign >/dev/null
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KCPASS" "$KC" >/dev/null

restore_state

"$OPENSSL" x509 -in "$DIR/cert.pem" -noout -fingerprint -sha1 | cut -d= -f2 | tr -d ':' | tr 'a-f' 'A-F' \
  > "$DIR/identity.sha1"
SHA1="$(cat "$DIR/identity.sha1")"
if ! security find-identity -p codesigning "$KC" | grep -qF "$SHA1 \"$NAME\""; then
  echo "The identity did not land in $KC." >&2
  exit 1
fi
SETUP_DONE=1
echo "Made \"$NAME\" ($SHA1) in $DIR"
echo "By hand, once: save $DIR/discjockey-release.p12 and the password in $DIR/p12.pass in your password manager."
