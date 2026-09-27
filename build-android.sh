#!/bin/sh
set -eu
: "${NDK:?set NDK to the NDK LLVM toolchain directory}"
: "${CC:=$NDK/bin/clang --target=aarch64-linux-android30}"
cd "$(dirname "$0")/src"
make clean
make passt CC="$CC" TARGET=aarch64-linux-android30 LDFLAGS="${LDFLAGS:--static}"
file passt
sha256sum passt
stat -c "%s bytes" passt
