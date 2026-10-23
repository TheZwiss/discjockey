#!/bin/sh
# Builds the static arm64 ffmpeg and ffprobe Discjockey.app ships, from FFmpeg's own source release (spec
# public-release §6.2). packaging/fetch_tools.py runs it on a cache miss, after checking the source tarball against
# the SHA-256 that packaging/tools.json pins, and passes tools.json's "configure" list as the arguments after <out>.
# That list links no external library: only FFmpeg's own code and macOS system libraries (libSystem, zlib, bzip2, and
# the CoreFoundation, Security (HTTPS), CoreVideo and CoreMedia frameworks), so nothing third-party is compiled in
# (packaging/licenses/ffmpeg.txt).
#
# usage: sh packaging/build_ffmpeg.sh <ffmpeg-X.Y.Z.tar.xz> <out folder> <configure argument>...
# Needs the Xcode command line tools (clang, make); nothing from Homebrew. The minimum macOS comes from the
# -mmacosx-version-min in the configure arguments.
set -eu

[ $# -ge 2 ] || { echo "usage: build_ffmpeg.sh <source.tar.xz> <out> <configure argument>..." >&2; exit 2; }
tarball=$1
out=$2
shift 2
# absolute before the cd into the source: the workflows pass relative paths (--cache dist/cache)
case $tarball in /*) ;; *) tarball=$PWD/$tarball ;; esac
case $out in /*) ;; *) out=$PWD/$out ;; esac

[ "$(uname -s)" = Darwin ] && [ "$(uname -m)" = arm64 ] || { echo "build_ffmpeg: needs an Apple Silicon Mac" >&2; exit 1; }

work=$(mktemp -d "${TMPDIR:-/tmp}/discjockey-ffmpeg.XXXXXX")
trap 'rm -rf "$work"' EXIT INT TERM

tar -xf "$tarball" -C "$work"
src=$(find "$work" -mindepth 1 -maxdepth 1 -type d -name 'ffmpeg-*' | head -n 1)
[ -n "$src" ] || { echo "build_ffmpeg: $tarball holds no ffmpeg-* folder" >&2; exit 1; }

cd "$src"
# a clean environment: no Homebrew pkg-config paths or flags leak into the configuration
env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin HOME="$work" TMPDIR="$work" ./configure "$@" > "$work/configure.log" 2>&1 || {
  tail -n 40 ffbuild/config.log >&2 2>/dev/null || tail -n 40 "$work/configure.log" >&2
  echo "build_ffmpeg: configure failed" >&2
  exit 1
}
jobs=$(sysctl -n hw.ncpu)
env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin HOME="$work" TMPDIR="$work" make -j"$jobs" ffmpeg ffprobe > "$work/make.log" 2>&1 || {
  tail -n 40 "$work/make.log" >&2
  echo "build_ffmpeg: make failed" >&2
  exit 1
}

# clang and ld also search /usr/local by default: a zlib or bzip2 from a package manager there must not end up linked.
# Only macOS's own libraries are allowed (the System Libraries the licence notice names).
for program in ffmpeg ffprobe; do
  foreign=$(otool -L "$program" | tail -n +2 | awk '{print $1}' | grep -Ev '^(/usr/lib/|/System/Library/)' || true)
  [ -z "$foreign" ] || { echo "build_ffmpeg: $program links libraries outside macOS: $foreign" >&2; exit 1; }
done

mkdir -p "$out"
for program in ffmpeg ffprobe; do
  cp "$program" "$out/$program"
  chmod 755 "$out/$program"
done
