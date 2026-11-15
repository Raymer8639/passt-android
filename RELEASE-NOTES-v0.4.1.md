# passt-android v0.4.1

v0.4.1 tightens the inherited-socket mode used by the Android/Neoproot integration. It is a
hardening release: the network data path, upstream baseline (official `7380393`) and the
IPv4/IPv6 behaviour are unchanged from v0.4.0.

## What changed

The opt-in `PASST_ANDROID_NO_ISOLATION=1|yes` mode is now validated **once**, after all
command-line parsing, and the result is stored in the context. Configuration, user isolation,
prefork isolation and the neighbour-notification path read that single committed flag, so they can
no longer disagree about whether the caller is in this mode.

The contract is explicit and narrow:

- `MODE_PASST` only (no `--splice-only`),
- an `--fd` that is a **connected** `AF_UNIX` `SOCK_STREAM` socket,
- an existing **non-root, non-setid** identity: `ruid==euid==suid` and `rgid==egid==sgid`,
  all non-zero,
- `--runas` is **refused** (the mode keeps the caller's credentials, so an override could not be
  honoured) instead of being silently ignored.

Anything that does not satisfy the contract is refused with a message naming the requirement.
A legal Android app keeps its own UID/GID and supplementary groups (Android denies
`setgroups()`), and still runs the capability clamp, the dumpable / no-new-privs fallback and the
seccomp steps.

**This is not a sandbox.** A connected socket is not evidence that the parent applied one; the
existing warning and documentation are unchanged.

## Validation

- 29-case state matrix over the production functions (`src/test/prepatched-contract.py`), including
  every refusal path and a legal socketpair.
- Host binaries build with `-Werror`; `check-tcp`, `check-android` and the new
  `check-prepatched` target run in CI.
- NDK r29 / API 30 static Android build: AArch64, no `INTERP`, no dynamic section, all LOAD
  segments 16 KiB aligned.
- Untraced Termux host: `strace` shows **no** `setgroups/setuid/setgid/setres*` in this mode, while
  `PR_CAPBSET_DROP` (64×), `capset`, `PR_SET_DUMPABLE`, `PR_SET_NO_NEW_PRIVS` and
  `PR_SET_SECCOMP` still run. The same binary without the opt-in still takes the full
  `isolate_user()` path.

## Boundaries

- Root/setid refusals are exercised through a controlled credential seam; they were not observed on
  a real root host.
- A glibc host binary cannot start inside the development container (`/proc/self/uid_map` is
  hidden; the v0.4.0 baseline fails identically). CI runs the host configuration regression on a
  normal Linux runner.

## Assets

Static `aarch64` Android binary (`passt-android-arm64`), built from this tag with
`VERSION=v0.4.1`, plus `SHA256SUMS`.
