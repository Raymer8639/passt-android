#!/bin/sh
set -eu
: "${NDK:?set NDK to the NDK LLVM toolchain directory}"
: "${CC:=$NDK/bin/clang --target=aarch64-linux-android30}"
REPO_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
: "${BUILD_DIR:=$REPO_DIR/.build/android}"
mkdir -p "$BUILD_DIR"
BUILD_DIR=$(CDPATH= cd -- "$BUILD_DIR" && pwd)
case "$BUILD_DIR/" in
    /|"$REPO_DIR/"|"$REPO_DIR/src/"*)
        echo "BUILD_DIR must be a separate directory outside src" >&2; exit 1 ;;
esac
cp -R "$REPO_DIR/src/." "$BUILD_DIR/"
make -C "$BUILD_DIR" clean
make -C "$BUILD_DIR" passt CC="$CC" TARGET=aarch64-linux-android30 \
    VERSION="${VERSION:-2026_11_11.7380393-android}" LDFLAGS="${LDFLAGS:--static}"
file "$BUILD_DIR/passt"
sha256sum "$BUILD_DIR/passt"
stat -c "%s bytes" "$BUILD_DIR/passt"
