# passt-android v0.4.0

v0.4.0 updates the Android/bionic ARM64 fork to official passt commit
[`7380393df27ec3ae4aacb40b6f9f25f75a11acf5`](https://passt.top/passt/commit/?id=7380393df27ec3ae4aacb40b6f9f25f75a11acf5),
including all 20 commits after `df90211`.

The update includes the small-MSS and FIN-only duplicate-ACK fixes, virtqueue
iovec bounds, splice latency fix, forwarding-rule rollback, DHCP option/boot
configuration with option overload and RFC 3396 splitting, and upstream address
and fd/namespace API changes. Linux policy updates are included as well.

Android compatibility has been replayed against those APIs. Explicit IPv4/IPv6
addresses, prefixes, gateways and DNS still work without route netlink in
prepatched mode. IPv6 local configuration initialises its inbound/NAT address
state, and IPv6-only mode requires an explicit IPv6 address. The ordered
uid_map → setgroups=deny → gid_map sequence remains intact with non-fatal
mapping warnings.

## Verified source candidate

- Complete native host binaries built with `-Werror`; `make check-tcp`,
  configuration/fd/mapping regressions and 13 bounded startup cases passed.
- Full Android aarch64 build with NDK r29 / API30 linked statically. ELF checks
  confirmed AArch64, the Android ABI note, no interpreter and no NEEDED entries.
- Termux IPv4 **10/10** and full IPv6 **15/15** gates passed with kernel
  7.2-rc4, matching stub/umnet and an isolated Alpine 3.21.3 root.
- DNS-disabled checks passed with only already-unscored DNS/TCP workload omitted
  by a scratch wrapper; production gate scoring was unchanged.

These results apply to source commit `2343c2edbbdc5bda10e9a22284e2ce3a3e2cdd81`
and the tested snapshot binary SHA256
`b583da58837015fa13125064d1086f657ddbb7d9578acc3e23fdda3028f5843f`.
They identify the pre-release source candidate, not the final version-labelled
release asset. The final asset is rebuilt from the release tag with
`VERSION=v0.4.0`, then its embedded version and ELF properties are checked.
No new long soak or real fault-injection run is claimed.

## Compatibility notes

`PASST_ANDROID_NO_ISOLATION=1` or `yes` remains an explicit opt-in requiring a
connected inherited socket. Ordinary `--fd` without the opt-in keeps upstream
discovery and isolation; pasta `--pass-fds` does not enable Android mode.

Prepatched mode skips credential changes and namespace isolation. An explicit
root caller remains root, and `--runas` is not applied. Connectedness does not
prove AF_UNIX/SOCK_STREAM, framing, or an existing parent sandbox. The caller
must provide the proper framed stream and its own isolation policy. The seccomp
filter and capability clamp still apply.

## Build the release asset

From the release-tag checkout:

```sh
env -i PATH=/usr/bin:/bin \
  NDK=/path/to/android-ndk-r29/toolchains/llvm/prebuilt/linux-x86_64 \
  VERSION=v0.4.0 ./build-android.sh
```

The static Android aarch64 binary is `.build/android/passt` by default. Set
`BUILD_DIR` to use another directory outside `src/`. The script prints its
SHA256 and size. Without explicit `VERSION`, the developer build uses the
upstream snapshot label rather than v0.4.0.
