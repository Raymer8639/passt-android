# Changelog

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
