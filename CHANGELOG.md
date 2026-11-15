# Changelog

## v0.4.1 — 2026-11-15

### Inherited-socket mode is validated once, before isolation

- Replace the ad-hoc predicate with `conf_prepatched()`: after all command-line
  parsing, it decides the mode **once** and stores it in `ctx`. Configuration,
  user isolation, prefork isolation and the neighbour-notification path all read
  that one committed flag (`fd_prepatched()`), so the halves can never disagree.
- The contract is now explicit and narrow: `MODE_PASST` without `--splice-only`,
  `PASST_ANDROID_NO_ISOLATION=1|yes`, an `--fd` that is a *connected* `AF_UNIX`
  `SOCK_STREAM` socket, and an existing non-root non-setid identity
  (`ruid==euid==suid`, `rgid==egid==sgid`, all non-zero). Anything else is
  refused with a message that names the requirement, instead of silently
  shortening the isolation path.
- `--runas` is refused in this mode rather than ignored: the contract keeps the
  caller's credentials, so an override could not be honoured.
- A legal Android app keeps its own UID/GID and supplementary groups (no
  `setgroups()`/setuid, which Android denies) and still runs the capability
  clamp, dumpable/no-new-privs fallback and seccomp steps. The explicit
  delegation is not evidence that a parent sandbox exists; the documentation
  keeps saying so.

### Validation

- `src/test/prepatched-contract.py` — 29-case matrix over the production
  functions: legal socketpair accepted; pipe, unconnected AF_UNIX, `SOCK_DGRAM`,
  connected `AF_INET`, missing fd, `MODE_PASTA`, `MODE_VU`, `--splice-only`,
  `--runas` (including a no-op one) and every root/setid credential shape
  refused.
- Host binaries build with `-Werror`; `check-tcp`, `check-android` and the new
  `check-prepatched` target pass in CI.
- NDK r29 / API 30 static Android build: AArch64, no interpreter, no dynamic
  section, every LOAD segment 16 KiB aligned.
- On an untraced Termux host (uid 10373): `strace` shows **no**
  `setgroups/setuid/setgid/setres*` calls, while `PR_CAPBSET_DROP`, `capset`,
  `PR_SET_DUMPABLE`, `PR_SET_NO_NEW_PRIVS` and `PR_SET_SECCOMP` still run.
  Without the opt-in the same binary still takes the full `isolate_user()` path.
- Boundaries: the root/setid refusals are exercised through a controlled
  credential seam, not on a real root host; the glibc host binary cannot start
  inside the development container because `/proc/self/uid_map` is hidden there
  (the v0.4.0 baseline fails identically).

## v0.4.0 — 2026-11-14

### Upstream update

- Import the complete 20-commit upstream interval from `df90211db4b08a06ed4e499ffa40bf8811100a2f` to `7380393df27ec3ae4aacb40b6f9f25f75a11acf5` from <https://passt.top/passt>.
- Include the small-MSS division-by-zero and FIN-only duplicate-ACK fixes, virtqueue iovec bounds, splice latency fix, and rollback of failed forwarding-rule updates.
- Include DHCP option configuration/boot support, option overload and RFC 3396 option splitting, plus the unified IPv4/IPv6 address structures and pasta inherited-fd API.
- Include upstream Linux AppArmor/SELinux policy and namespace updates. These do not remove Android system-policy restrictions.

### Android and inherited interface sockets

- Replay the Android/bionic compatibility and explicit `PASST_ANDROID_NO_ISOLATION=1|yes` mode against the new configuration and fd APIs. Ordinary `--fd` keeps upstream discovery and isolation without the opt-in.
- Preserve explicit IPv4/IPv6 addresses, prefixes, gateways and DNS without route netlink in prepatched mode. Initialise IPv6 local `addr_seen` for inbound/NAT and refuse IPv6-only mode when no explicit IPv6 address is present.
- Keep ordered independent `uid_map -> setgroups=deny -> gid_map` writes while adopting upstream non-fatal mapping warnings. A failed setgroups write still permits the gid_map attempt.
- Build in isolated `.build/android` and `.build/host` directories. `VERSION=v0.4.0` explicitly embeds the release version.

### Validation

- Source candidate: complete host binaries with `-Werror`, `make check-tcp`, configuration/fd/mapping regression checks, 13 bounded startup cases, full NDK r29/API30 static Android build and ELF checks passed.
- Termux source candidate: IPv4 10/10 and full IPv6 15/15 passed with an isolated Alpine 3.21.3 root and kernel 7.2-rc4.
- Existing prepatched limitations remain: no credential lowering or namespace isolation in opt-in mode; connectedness does not prove the parent has a sandbox or that the fd uses the required stream framing. No new soak or real fault-injection run is claimed.

See [the release notes](RELEASE-NOTES-v0.4.0.md) for candidate identity, validation boundaries and the release build command.
