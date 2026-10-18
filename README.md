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

`umnet` sets it because it creates the socketpair and owns the sandbox. A
caller that does not set it gets upstream behaviour, including when it passes a
socket with `--fd` -- silencing the sandbox for every `--fd` user was a bug, not
a feature. The variable is checked once, and `fd_prepatched()` additionally
requires a *connected* socket (`getpeername()`), so a listening or unconnected
descriptor fails at startup with a clear message instead of skipping isolation
and failing later.

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

In this mode passt runs as an ordinary unprivileged uid with no namespace
isolation. Its **seccomp filter still applies**, and it never had privileges to
lose. The default passt/pasta paths -- no `--fd`, or a `--fd` that is not a
socket -- are untouched and still take the full isolation sequence.

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

Build and copy `src/passt` to the device, then `./passt --version` and
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
