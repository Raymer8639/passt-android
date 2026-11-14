# Patch notes

The Android changes are **vendored into `src/`**, not applied as a patch, so a
build here needs no extra step. This directory records what the next person
rebasing onto a newer upstream needs to know.

## Rebasing onto a new upstream commit

1. Take the new upstream tree into `src/`.
2. Re-apply the Android changes listed in the top-level README's "Android
   changes" table. They are all guarded, so `git grep -n '__ANDROID__' src`
   finds most of them; the prepatched-socket mode is the exception and is
   identified by `fd_prepatched()`.
3. Update the upstream commit hash and version in `README.md` and the snapshot
   version in `build-android.sh`. Current upstream is
   `7380393df27ec3ae4aacb40b6f9f25f75a11acf5` (2026-11-14 verification).
   The full `df90211..7380393` interval is included, including existing
   MSS/FIN fixes; do not apply those fixes a second time.
4. Build in separate directories: `build-android.sh` defaults to `.build/android`,
   and the host job copies sources into `.build/host`. Run `make -C src check-tcp
   check-android CC=gcc`, then bounded `test/config-regression.py` against the
   host binary. CI checks static Android ELF, ordinary `--fd` without opt-in,
   and IPv4/IPv6 explicit configuration.
5. Local configuration now takes `struct ctx *` and uses `fwd_get_addr()` and
   `guest_addr` prefixes instead of removed `ip4.addr` / `ip6.addr` members.
   Keep IPv6 local `addr_seen` initialisation: `addr_fixed` prevents learning
   it from traffic. Upstream `--pass-fds` changes early fd handling; it does
   not enable the Android shortcut.
6. Keep uid_map -> setgroups=deny -> gid_map ordering. Upstream mapping write
   failures warn rather than abort; downstream attempts all three writes in
   that order and tolerates setgroups failure. Regression stubs procfs writes
   and covers all eight success/failure combinations.

The prepatched branch in `conf()` is the part to read closely: it covers
IPv4 *and* IPv6 (`conf_ip4_local()` and `conf_ip6_local()`), never opens a netlink
socket, and refuses `-6` without an explicit `-a`. A rebase that moves the
IPv6 configuration back to `conf_ip6()` reintroduces the Android start-up failure
(`Failed to get netlink socket` on `bind((0, 0))`).

## Why not a patch file

An earlier version of this repository carried `android-bionic.patch` with
instructions to apply it. It went stale the moment the source was vendored:
the patch described a tree nobody built any more, and reading it gave a
misleading picture of what was actually shipped. Prefer the guarded source.
