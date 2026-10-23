#!/bin/bash
# Imports the "Discjockey Release" code-signing identity from its .p12 into a keychain of its own, in the layout that
# packaging/sign_app.py reads (spec public-release §6.3): the same three files scripts/make_signing_identity.sh writes.
# For CI: the release workflow decodes the repository secret into a .p12 and runs this on a fresh runner. Never
# prompts: the keychain gets a fresh random password (kept next to it, mode 600) and the partition list that lets
# codesign use the key without asking. The keychain search list and the default keychain are left as they are.
# Only an identity named "Discjockey Release" is accepted; any other certificate in the file is refused.
#
# usage: scripts/import_signing_identity.sh <file.p12>
#   SIGNING_P12_PASSWORD     the .p12's password (required, from the environment so it never shows in `ps`)
#   DISCJOCKEY_SIGNING_DIR   where it goes (required: no default, so CI can never write into a home folder)
#   OPENSSL                  the openssl to read the .p12 with (default: /usr/bin/openssl; LibreSSL or OpenSSL 3 both work)
# Refuses (exit 1) when the folder already holds an identity, the file is missing, the password is empty or wrong, or
# the file holds no "Discjockey Release" certificate; exit 2 for a usage error. A refusal touches no keychain.
set -euo pipefail
NAME="Discjockey Release"

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <file.p12>   (password in SIGNING_P12_PASSWORD, target folder in DISCJOCKEY_SIGNING_DIR)" >&2
  exit 2
fi
P12="$1"
if [ -z "${DISCJOCKEY_SIGNING_DIR:-}" ]; then
  echo "DISCJOCKEY_SIGNING_DIR is not set. It has no default here: name the folder the identity goes into." >&2
  exit 2
fi
DIR="$DISCJOCKEY_SIGNING_DIR"
KC="$DIR/discjockey-release.keychain-db"

if [ ! -f "$P12" ]; then
  echo "The file $P12 does not exist." >&2
  exit 1
fi
if [ -z "${SIGNING_P12_PASSWORD:-}" ]; then
  echo "SIGNING_P12_PASSWORD is empty or not set." >&2
  exit 1
fi
found=""
[ -e "$DIR/identity.sha1" ] && found="identity.sha1"
[ -e "$KC" ] && found="${found:+$found and }discjockey-release.keychain-db"
if [ -n "$found" ]; then
  echo "A signing identity already exists in $DIR ($found). Not replacing it (a new one makes every user grant access again)." >&2
  exit 1
fi

# Which openssl: macOS's own /usr/bin/openssl (LibreSSL) reads the -legacy PKCS#12 that make_signing_identity.sh exports
# as it is; OpenSSL 3 (Homebrew, or first on PATH on a runner) needs `-legacy` for it, which LibreSSL doesn't know.
# So: OPENSSL if set, else /usr/bin/openssl, else the first openssl on PATH; an OpenSSL 3 is tried without, then with `-legacy`.
OPENSSL="${OPENSSL:-}"
if [ -z "$OPENSSL" ] && [ -x /usr/bin/openssl ]; then OPENSSL=/usr/bin/openssl; fi
if [ -z "$OPENSSL" ]; then OPENSSL="$(command -v openssl || true)"; fi   # `|| true`: under set -e a failed lookup would exit silently
if [ -z "$OPENSSL" ]; then
  echo "Needs openssl to read the .p12 (macOS has /usr/bin/openssl; or set OPENSSL=<path>)." >&2
  exit 1
fi

# Before any keychain exists: the password must open the file, and the certificate in it must carry the right name.
# The password goes in by variable name (`-passin env:`), never as an argument.
read_certs() { "$OPENSSL" pkcs12 "$@" -in "$P12" -nokeys -clcerts -passin env:SIGNING_P12_PASSWORD 2>/dev/null; }
cert="$(read_certs || true)"
if [ -z "$cert" ] && "$OPENSSL" version 2>/dev/null | grep -q '^OpenSSL 3'; then
  cert="$(read_certs -legacy || true)"
fi
if [ -z "$cert" ]; then
  echo "Could not open $P12: wrong password, or not a .p12 with a certificate in it." >&2
  exit 1
fi
# one certificate with a key, not several: a file with a second identity would import that one too
if [ "$(printf '%s\n' "$cert" | grep -c -- '-----BEGIN CERTIFICATE-----')" -gt 1 ]; then
  echo "$P12 holds more than one certificate with a key; it must hold only the \"$NAME\" identity. Not importing it." >&2
  exit 1
fi
subject="$(printf '%s\n' "$cert" | "$OPENSSL" x509 -noout -subject -nameopt multiline 2>/dev/null || true)"
if ! printf '%s\n' "$subject" | grep -qE "^[[:space:]]*commonName[[:space:]]*=[[:space:]]*${NAME}[[:space:]]*\$"; then
  echo "$P12 holds no \"$NAME\" code-signing identity. Not importing it." >&2
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

DIR_CREATED=0
SETUP_DONE=0
cleanup() {
  local status=$?
  trap - EXIT
  if [ "$SETUP_DONE" != 1 ]; then
    # a failed run must leave nothing behind that blocks the next one, and the keychain settings as they were
    if [ -e "$KC" ]; then security delete-keychain "$KC" >/dev/null 2>&1 || true; fi
    restore_state || echo "Could not restore the keychain search list; check: security list-keychains -d user" >&2
    if [ "$DIR_CREATED" = 1 ]; then
      rm -rf "$DIR"
      echo "Import failed; nothing was kept." >&2
    else
      rm -f "$DIR/keychain.pass" "$DIR/identity.sha1"
      echo "Import failed; the files this run made in $DIR were removed." >&2
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

head -c 24 /dev/urandom | base64 | tr -d '\n' > "$DIR/keychain.pass"
KCPASS="$(cat "$DIR/keychain.pass")"
security create-keychain -p "$KCPASS" "$KC"
security set-keychain-settings "$KC"   # no automatic lock
printf '%s\n' "$KCPASS" | security unlock-keychain "$KC"   # password on stdin, not in ps
# `security` takes these passwords only as arguments (they show in `ps` for a moment): create-keychain -p, import -P and
# set-key-partition-list -k. The keychain password is random and the keychain lives in this job's temp folder; the
# runner is private to the job and gone afterwards. Only unlock-keychain reads its password from stdin.
# The .p12 password is the long-lived one, and it also sits in `import -P`'s argv for the length of that one short
# process. Re-wrapping the .p12 under a throwaway password first would only trade it for a one-time one; it is kept as
# is because the job's runner is a fresh machine per job that no other process or user shares, and the secret is
# masked in the log.
security import "$P12" -k "$KC" -P "$SIGNING_P12_PASSWORD" -T /usr/bin/codesign >/dev/null
# same partition list as make_signing_identity.sh: codesign never asks for the key
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KCPASS" "$KC" >/dev/null

restore_state

# the SHA-1 as macOS lists it; exactly one "Discjockey Release" identity must have landed (certificate and key)
listing="$(security find-identity -p codesigning "$KC")"
hashes="$(printf '%s\n' "$listing" | sed -n "s/^[[:space:]]*[0-9][0-9]*)[[:space:]]*\([0-9A-F]\{40\}\)[[:space:]]*\"$NAME\".*/\1/p")"
if [ -z "$hashes" ] || [ "$(printf '%s\n' "$hashes" | wc -l | tr -d ' ')" != 1 ]; then
  echo "The file did not give exactly one \"$NAME\" code-signing identity in $KC." >&2
  exit 1
fi
printf '%s\n' "$hashes" > "$DIR/identity.sha1"
SETUP_DONE=1
echo "Imported \"$NAME\" ($hashes) into $DIR"
