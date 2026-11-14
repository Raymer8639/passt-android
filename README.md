# passt-android

**v0.4.0** — Android/bionic ARM64 port of passt, based on official upstream
commit `7380393df27ec3ae4aacb40b6f9f25f75a11acf5` (2026-11-11 snapshot).
The complete 20-commit update after `df90211` is included. See the
[changelog](CHANGELOG.md) and [v0.4.0 release notes](RELEASE-NOTES-v0.4.0.md).

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
env -i PATH=/usr/bin:/bin \
  NDK=/path/to/android-ndk-r29/toolchains/llvm/prebuilt/linux-x86_64 \
  VERSION=v0.4.0 ./build-android.sh
```

The result is `.build/android/passt`: static, Android API 30, aarch64.
`VERSION=v0.4.0` is passed explicitly to the compiler and embedded in
`passt --version`. Without `VERSION`, the developer build keeps the upstream
snapshot label `2026_11_11.7380393-android`; release builds must set it.
After the release tag is created, build from that checkout with the command
above and verify the binary version and ELF before uploading it.
`BUILD_DIR` can select another directory outside `src/`; sources and existing
binaries under `src/` are left intact. Static bionic is
intentional -- glibc binaries are rejected by Android seccomp before `main()`
(`set_robust_list` is killed with SIGSYS), and there is no glibc to link
against on the device anyway.

## The one behaviour switch: `PASST_ANDROID_NO_ISOLATION`

Upstream passt isolates itself: it creates user, mount, PID and IPC
namespaces, drops to nobody, and `pivot_root()`s into an empty directory. On
Android an app process may do none of that -- `unshare`, `clone(CLONE_NEWUSER)`
and `setgroups` are all refused -- so when the interface is an inherited socket
the isolation is skipped.

That skip is **opt-in**:

```sh
PASST_ANDROID_NO_ISOLATION=1 passt -f -F 5 ...
```

`umnet` sets it because it creates the socketpair and accepts responsibility
for the inherited interface and isolation policy. A
caller that does not set it gets upstream behaviour, including when it passes a
socket with `--fd` -- silencing the sandbox for every `--fd` user was a bug, not
a feature. The variable is checked once, and `fd_prepatched()` additionally
requires a *connected* socket (`getpeername()`). A listening or unconnected
descriptor takes ordinary discovery and isolation. Connectedness does not prove
AF_UNIX, stream framing, or an existing parent sandbox.

The same predicate decides whether passt may skip **host-interface discovery**.
A prepatched endpoint has no host interface to discover -- every guest-side
value comes from the caller (`-a`, `-g`, `-D`) -- and Android denies route
netlink to an app uid, so in that case passt does not open a netlink socket at
all. Anything that is not prepatched (`--fd` without the opt-in, or an `--fd`
that is not a connected socket) takes the upstream route: netlink discovery
plus isolation, with no half-applied shortcut.

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

The Android prepatched mode is an explicit choice by the parent, which must
provide a connected interface socket and its own isolation policy. With the
opt-in enabled, `fd_prepatched()` skips:

* the netlink probe, using the caller's explicit configuration instead -- for
  IPv4 *and* IPv6, so neither family needs `NETLINK_ROUTE`;
* `isolate_user()`, so no `setgroups()` and no user namespace;
* `isolate_prefork()`'s `unshare()` and mount/`pivot_root` sandbox, still
  dropping capabilities;
* the neighbour-notify netlink socket.

`make_ugid_map()` no longer treats a failed write to `/proc/<pid>/setgroups` as
fatal either.

IPv6 uses the same local mode as IPv4: the values come from the caller
(`-6 -a fd00::2/64 -g fe80::1 -D <dns>`), the prefix length is the one `-a`
carries and the gateway is the one `-g` names. Because there is no netlink
socket to ask, an IPv6 prepatched run with `-6` and no `-a` is refused with
`--fd with IPv6 needs an explicit -a address` rather than falling back to a
default prefix.

This mode is intended for an ordinary Android app uid. It skips credential
changes as well as namespace isolation: an explicit root caller remains root,
and `--runas` is not applied. A connected fd is not evidence of a sandbox.
The **seccomp filter and capability clamp still apply**. Callers must supply a
properly framed stream and provide their own isolation policy. Ordinary `--fd`
without the opt-in takes the full upstream discovery and isolation sequence.

That last claim is what the host job in CI verifies.

### Why no other transport is left on Android

passt can normally reach a network in several ways. On an ordinary Android app
process every one of them except an inherited socket is closed, and not by
configuration:

| path | what it needs | on an Android app process |
| --- | --- | --- |
| `tap` | `CAP_NET_ADMIN` (and `/dev/net/tun` access) to create the interface | no capabilities, no tun device |
| `pasta` | user namespaces to put the guest in one | `clone(CLONE_NEWUSER)` = `EINVAL`, `unshare()` = `EPERM` |
| vhost-user / vhost-kernel | a VMM, or `/dev/vhost-net` | neither exists in an app process |
| an in-process switch (`bess`, `vde`) | a tap at the edge | the same `tap` problem |

What remains is the `fd` transport: whoever owns the L2 side -- in practice a
UML harness, or any parent that already holds an interface fd -- hands passt a
socket, and passt only moves frames and terminates TCP/UDP/ICMP on the host.
That is why prepatched mode is not a workaround around the port: on the phone it
is the only startup path passt has.

## Verification

Build and copy `.build/android/passt` to the device, then `./passt --version` and
`./passt --help` must exit 0 without SIGSYS.

For the dataplane, this binary is the passt end of the UML `vec0` bridge in
`Raymer8639/linux-um-arm64`. The harness there runs the full check and judges
DHCP, DNS, ICMP and TCP from the guest's own output; see
`tools/um-arm64/doc/90-networking.md` in that repository.

The source candidate for v0.4.0 was verified on 2026-11-14: complete native
host builds of passt/pasta, passt-repair and pesto passed with `-Werror`, the
MSS/FIN regressions and Android configuration/fd/mapping checks passed, and
NDK r29/API30 produced a static Android aarch64 ELF with no interpreter or
shared-library dependencies. The bounded host startup probes covered 13 cases.

On Termux, the same source candidate passed IPv4 **10/10** and full IPv6
**15/15** gates with kernel 7.2-rc4, a matching stub/umnet and an isolated
Alpine 3.21.3 root. DNS-disabled checks also passed with only the unscored DNS
and TCP workload omitted by a scratch wrapper; the gate scoring stayed intact.
These results belong to the tested snapshot candidate. The final tagged release
asset is rebuilt separately with `VERSION=v0.4.0`; its version and ELF must be
checked again. Historical fault/soak records are not new v0.4.0 test runs.

The host startup probes check path selection and explicit configuration; they
do not assert the process credentials or namespace state. See the release notes
for the tested candidate identity and the prepatched-mode limitations.

## Upstream

Source: <https://passt.top/passt>, commit
`7380393df27ec3ae4aacb40b6f9f25f75a11acf5` (official master/HEAD checked
2026-11-14). All 20 commits after `df90211` are included. The prepatched-socket
behaviour remains downstream; its current credential and fd validation semantics
are not an upstream-ready sandbox interface. No RFC has been sent.

The inherited-fd API now uses upstream `conf_fds()` and
`isolate_fds(ctx, argc, argv)`. The pasta-only `--pass-fds` option preserves fds
for a spawned command; it does not request prepatched mode. Guest addresses and
prefix lengths use upstream `guest_addr` entries (IPv4 prefixes store +96).
Explicit IPv6 local configuration also initialises `addr_seen` for inbound/NAT.

Run `make -C src check-tcp check-android CC=gcc` and the bounded
`python3 src/test/config-regression.py .build/host/passt` against a host build.
CI uses separate `.build/android` and `.build/host` directories.

## Layout

```
build-android.sh      the build, as CI runs it
src/                  vendored upstream tree plus the Android changes
patches/              notes for the next upstream rebase
```
