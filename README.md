# passt-android

Android/bionic ARM64 port of passt, maintained from upstream commit df90211.

## Build

Requires Android NDK r29 and an aarch64 Linux host. From this directory:

```sh
NDK=/home/Raymer/android-sdk/ndk/29.0.14206865/toolchains/llvm/prebuilt/linux-x86_64
CC="$NDK/bin/clang --target=aarch64-linux-android30" LDFLAGS=-static ./build-android.sh
```

The resulting static binary is `src/passt` (Android API 30, aarch64). Static bionic is intentional: glibc binaries are not usable in Termux because Android seccomp rejects set_robust_list.

## Verification

Copy `src/passt` to Termux and run `./passt --version` and `./passt --help`; both must exit 0. The network dataplane still requires normal Termux socket and permission setup.

## Upstream

Source: https://passt.top/passt, commit `df90211`. The source under `src` is a vendored snapshot; Android-only changes are guarded by `__ANDROID__`.
