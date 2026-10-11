# passt-android

Android/bionic ARM64 port of passt, maintained from upstream commit `df90211`
(version 2026_09_25.df90211).

passt runs a guest's TCP/IP stack in userspace, so a guest can reach the
network with no root, no TAP device and no capabilities. On Android that is the
only door left open: `tap` needs `CAP_NET_ADMIN`, `raw`/`gre`/`l2tpv3` need raw
sockets, and a `bess`/`vde` switch still needs a tap to reach the world. What
remains is UML's `fd` transport, which just reads and writes Ethernet frames on
a descriptor somebody else set up -- and passt behind that descriptor.

This repository exists to keep that port buildable and honest. It is a
**vendored snapshot**: upstream sources live under `src/`, so a build here needs
no patching step.

## Build

```sh
NDK=/path/to/android-ndk-r29/toolchains/llvm/prebuilt/linux-x86_64 \
  ./build-android.sh
```

The result is `src/passt`: static, Android API 30, aarch64. Static bionic is
intentional -- glibc binaries are rejected by Android seccomp before `main()`
(`set_robust_list` is killed with SIGSYS), and there is no glibc to link
against on the device anyway.

## CI

`.github/workflows/build.yml` cross-compiles with the NDK, checks the artifact
really is a static Android aarch64 binary (no interpreter, no `NEEDED`
entries), and separately builds for the host to confirm the Android changes
have not disturbed the ordinary passt path.

## Android changes

Everything Android-specific is guarded, so the upstream build is unaffected:

| change | why |
| --- | --- |
| `android_compat.h` | `MAXNS`/`MAXDNSRCH`, `_PATH_LOG`, bionic's IPv6 macros |
| `ip.h`, `common.h`, `tcp.c` guards | UAPI differences between glibc and bionic |
| `virtio.c`: `vring_need_event` | not provided by bionic |
| `util.c`: `/proc/self/uid_map` fallback | the file is hidden on Android |
| `util.c`, `isolation.c`, `conf.c`, `passt.c`: prepatched-socket mode | see below |

### Prepatched-socket mode

An Android app process cannot create namespaces. Measured on Termux (Android
13, kernel 5.15.194, ordinary app uid):

| call | result |
| --- | --- |
| `socket(AF_NETLINK, SOCK_RAW, NETLINK_ROUTE)` | `EPERM` |
| `setgroups(0, NULL)` | `SIGSYS` (seccomp kills the process) |
| `clone(CLONE_NEWUSER)` | `EINVAL` |
| `unshare(CLONE_NEWNS\|CLONE_NEWIPC\|CLONE_NEWUTS)` | `EPERM` |

passt's normal startup depends on all four. But when `--fd` is a socket handed
over by a parent that already set the interface up (an UML harness, a VMM), none
of that work is needed or possible. `fd_prepatched()` detects exactly that case
and skips:

* the netlink probe, using the caller's explicit IPv4 configuration instead;
* `isolate_user()`, so no `setgroups()` and no user namespace;
* `isolate_prefork()`'s `unshare()` and mount/`pivot_root` sandbox, still
  dropping capabilities;
* the neighbour-notify netlink socket.

`make_ugid_map()` no longer treats a failed write to `/proc/<pid>/setgroups` as
fatal either.

In this mode passt runs as an ordinary unprivileged uid with no namespace
isolation. Its **seccomp filter still applies**, and it never had privileges to
lose. The default passt/pasta paths -- no `--fd`, or a `--fd` that is not a
socket -- are untouched and still take the full isolation sequence.

That last claim is what the host job in CI verifies.

## Verification

Build and copy `src/passt` to the device, then `./passt --version` and
`./passt --help` must exit 0 without SIGSYS.

For the dataplane, this binary is the passt end of the UML `vec0` bridge in
`Raymer8639/linux-um-arm64`. The harness there runs the full check and judges
DHCP, DNS, ICMP and TCP from the guest's own output; see
`tools/um-arm64/doc/90-networking.md` in that repository.

## Upstream

Source: <https://passt.top/passt>, commit `df90211`. The prepatched-socket
behaviour is a downstream change and a reasonable candidate to offer upstream:
"run correctly when handed an interface socket and denied namespace creation"
is a normal thing for passt to support.

## Layout

```
build-android.sh      the build, as CI runs it
src/                  vendored upstream tree plus the Android changes
patches/              notes for the next upstream rebase
```
