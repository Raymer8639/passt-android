# passt-android

Android/bionic ARM64 port of passt, maintained from upstream commit `7380393df27ec3ae4aacb40b6f9f25f75a11acf5`
(snapshot 2026_11_11.7380393).

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

The result is `.build/android/passt`: static, Android API 30, aarch64.
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

passt's normal startup depends on all four. But when `--fd` is a socket handed
over by a parent that already set the interface up (an UML harness, a VMM), none
of that work is needed or possible. `fd_prepatched()` detects exactly that case
and skips:

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

Device evidence is archived there too: a full network gate run
(`docs/evidence/2026-10-17-umnet-network.json`, 9/9 checks) names this binary by
SHA256, `docs/evidence/faults/` holds the judged link-drop / kernel-kill /
guest-panic scenarios, and the soak tool repeats the gate under
`--minutes`/`--rounds` bounds. The host job in CI is what guarantees the
ordinary passt path has not changed; the device records are what prove the
Android path ran.

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
