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
3. Update the upstream commit hash and version in `README.md`.
4. Run CI: the android job must still produce a static Android aarch64 binary,
   and the host job must still build and still refuse to skip isolation when
   `--fd` is absent.

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
