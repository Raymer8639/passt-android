#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""State matrix for the prepatched contract, calling production code directly.

conf_prepatched()/fd_prepatched() are compiled from the real util.c and linked
with the real log.c, so every refusal below is the production decision and the
production fatal path -- not a log-string match in a shell.  Each case runs in
its own process because a refusal exits.

The credentials branch (root, setuid, setgid) cannot be reached on a non-root
test host.  A second binary builds util.c with
-Dgetresuid=seam_getresuid -Dgetresgid=seam_getresgid and supplies those
symbols from a compile-time seam: with PASST_TEST_CREDS unset it forwards to
the real syscall, with it set it returns the six values given.  Cases run
against that binary are labelled "seam": they are a controlled negative test,
not an observation under a real root or setuid identity.
"""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <netinet/in.h>
#include <sys/socket.h>

#include "passt.h"
#include "util.h"

/* Unused cleanup state referenced by production fatal logging. */
struct ctx passt_ctx;
int pcap_fd = -1;

#ifdef CREDS_SEAM
#include <sys/syscall.h>
/* Compile-time seam for util.c: see the module docstring.  Returns the six
 * values from PASST_TEST_CREDS when set, the caller's real credentials
 * otherwise, so the same binary covers both the fake and the real branch. */
static bool seam_values(unsigned long v[6])
{
    const char *s = getenv("PASST_TEST_CREDS");

    if (!s)
        return false;
    if (sscanf(s, "%lu:%lu:%lu:%lu:%lu:%lu",
               &v[0], &v[1], &v[2], &v[3], &v[4], &v[5]) != 6) {
        fprintf(stderr, "bad PASST_TEST_CREDS: %s\n", s);
        _exit(97);
    }
    return true;
}

int seam_getresuid(uid_t *r, uid_t *e, uid_t *s)
{
    unsigned long v[6];

    if (seam_values(v)) {
        *r = v[0];
        *e = v[1];
        *s = v[2];
        return 0;
    }
    return syscall(SYS_getresuid, r, e, s) ? -1 : 0;
}

int seam_getresgid(gid_t *r, gid_t *e, gid_t *s)
{
    unsigned long v[6];

    if (seam_values(v)) {
        *r = v[3];
        *e = v[4];
        *s = v[5];
        return 0;
    }
    return syscall(SYS_getresgid, r, e, s) ? -1 : 0;
}
#endif

int main(int argc, char **argv)
{
    const char *name, *opt = "1", *runas = NULL;
    struct ctx c = { 0 };
    char runas_self[64];
    int sv[2], p[2];

    assert(argc == 2);
    name = argv[1];

    /* Baseline contract inputs: MODE_PASST, no --runas, opt-in, and a
     * connected AF_UNIX SOCK_STREAM endpoint.  Each case weakens exactly
     * one of them. */
    c.mode = MODE_PASST;
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, sv) == 0);
    c.fd_tap = sv[1];
    snprintf(runas_self, sizeof(runas_self), "%u:%u",
             (unsigned)getuid(), (unsigned)getgid());

    if (!strcmp(name, "env_unset")) {
        opt = NULL;
    } else if (!strcmp(name, "env_zero")) {
        opt = "0";
    } else if (!strcmp(name, "env_true")) {
        opt = "true";
    } else if (!strcmp(name, "env_empty")) {
        opt = "";
    } else if (!strcmp(name, "env_yes")) {
        opt = "yes";
    } else if (!strcmp(name, "mode_pasta")) {
        c.mode = MODE_PASTA;
    } else if (!strcmp(name, "mode_vu")) {
        c.mode = MODE_VU;
    } else if (!strcmp(name, "splice_only")) {
        c.splice_only = true;
    } else if (!strcmp(name, "runas_name")) {
        runas = "nobody";
    } else if (!strcmp(name, "runas_self")) {
        runas = runas_self;	/* no-op override: still refused */
    } else if (!strcmp(name, "no_fd")) {
        c.fd_tap = -1;
    } else if (!strcmp(name, "pipe")) {
        assert(pipe(p) == 0);
        c.fd_tap = p[0];
    } else if (!strcmp(name, "unconnected")) {
        c.fd_tap = socket(AF_UNIX, SOCK_STREAM, 0);
        assert(c.fd_tap >= 0);
    } else if (!strcmp(name, "dgram")) {
        assert(socketpair(AF_UNIX, SOCK_DGRAM, 0, sv) == 0);
        c.fd_tap = sv[1];
    } else if (!strcmp(name, "inet")) {
        struct sockaddr_in addr = {
            .sin_family = AF_INET,
            .sin_addr.s_addr = htonl(INADDR_LOOPBACK),
        };
        socklen_t len = sizeof(addr);
        int listener = socket(AF_INET, SOCK_STREAM, 0);

        assert(listener >= 0);
        assert(!bind(listener, (struct sockaddr *)&addr, sizeof(addr)));
        assert(!getsockname(listener, (struct sockaddr *)&addr, &len));
        assert(!listen(listener, 1));
        c.fd_tap = socket(AF_INET, SOCK_STREAM, 0);
        assert(c.fd_tap >= 0);
        assert(!connect(c.fd_tap, (struct sockaddr *)&addr, sizeof(addr)));
    } else if (!strcmp(name, "fresh")) {
        /* fd_prepatched() before any validation: the committed flag, not a
         * probe of the descriptor. */
        printf("RESULT case=%s prepatched=%d fd_prepatched=%d\n",
               name, c.prepatched, fd_prepatched(&c));
        return 0;
    }

    if (opt)
        assert(!setenv("PASST_ANDROID_NO_ISOLATION", opt, 1));
    else
        assert(!unsetenv("PASST_ANDROID_NO_ISOLATION"));

    conf_prepatched(&c, runas);
    printf("RESULT case=%s prepatched=%d fd_prepatched=%d\n",
           name, c.prepatched, fd_prepatched(&c));

    if (!strcmp(name, "committed")) {
        /* The decision is committed: closing the descriptor and dropping the
         * opt-in afterwards must not change what isolation.c reads. */
        close(c.fd_tap);
        assert(!unsetenv("PASST_ANDROID_NO_ISOLATION"));
        printf("RESULT case=%s fd_closed prepatched=%d fd_prepatched=%d\n",
               name, c.prepatched, fd_prepatched(&c));
    }

    return 0;
}
'''

BASE_FLAGS = ["-D_GNU_SOURCE", "-D_XOPEN_SOURCE=700", "-DPAGE_SIZE=4096",
              '-DVERSION="regression"', "-std=c11", "-O1", "-Wall", "-Wextra",
              "-Werror", "-ffunction-sections", "-fdata-sections",
              "-Wl,--gc-sections", "-fsanitize=undefined",
              "-fno-sanitize-recover=all"]

REFUSE = {
    "mode": "Prepatched mode requires MODE_PASST without --splice-only",
    "runas": "Prepatched mode does not support --runas",
    "creds": "Prepatched mode requires a non-root, non-setid UID and GID",
    "fd": "Prepatched mode requires --fd with a connected AF_UNIX SOCK_STREAM socket",
    "peer": "Prepatched mode requires a connected AF_UNIX socket",
    "type": "Prepatched mode requires SOCK_STREAM framing",
}

SELF_CREDS = "10373:10373:10373:10373:10373:10373"
ROOT_CREDS = "0:0:0:0:0:0"

# (label, harness case, binary, PASST_TEST_CREDS, expected)
CASES = [
    ("legal", "legal", "real", None, "pass"),
    ("legal env=yes", "env_yes", "real", None, "pass"),
    ("committed decision", "committed", "real", None, "pass"),
    ("env unset", "env_unset", "real", None, "off"),
    ("env=0", "env_zero", "real", None, "off"),
    ("env=true", "env_true", "real", None, "off"),
    ("env empty", "env_empty", "real", None, "off"),
    ("fresh ctx", "fresh", "real", None, "off"),
    ("MODE_PASTA", "mode_pasta", "real", None, "mode"),
    ("MODE_VU", "mode_vu", "real", None, "mode"),
    ("--splice-only", "splice_only", "real", None, "mode"),
    ("--runas nobody", "runas_name", "real", None, "runas"),
    ("--runas self (no-op)", "runas_self", "real", None, "runas"),
    ("--fd absent", "no_fd", "real", None, "fd"),
    ("--fd is a pipe", "pipe", "real", None, "fd"),
    ("AF_UNIX unconnected", "unconnected", "real", None, "peer"),
    ("AF_UNIX SOCK_DGRAM", "dgram", "real", None, "type"),
    ("AF_INET connected", "inet", "real", None, "peer"),
    # Compile-time credential seam -- controlled negatives, see docstring.
    ("seam: legal identity", "legal", "seam", SELF_CREDS, "pass"),
    ("seam: real credentials", "legal", "seam", None, "pass"),
    ("seam: root", "legal", "seam", ROOT_CREDS, "creds"),
    ("seam: root uid only", "legal", "seam", "0:0:0:10373:10373:10373", "creds"),
    ("seam: root gid only", "legal", "seam", "10373:10373:10373:0:0:0", "creds"),
    ("seam: euid 0", "legal", "seam", "10373:0:10373:10373:10373:10373", "creds"),
    ("seam: suid 0", "legal", "seam", "10373:10373:0:10373:10373:10373", "creds"),
    ("seam: sgid 0", "legal", "seam", "10373:10373:10373:10373:10373:0", "creds"),
    ("seam: root and no fd", "no_fd", "seam", ROOT_CREDS, "creds"),
    ("seam: root and --runas", "runas_name", "seam", ROOT_CREDS, "runas"),
    ("seam: root and MODE_PASTA", "mode_pasta", "seam", ROOT_CREDS, "mode"),
]


def run(binary, case, creds, env_base):
    env = dict(env_base)
    if creds:
        env["PASST_TEST_CREDS"] = creds
    p = subprocess.run([str(binary), case], capture_output=True, timeout=10,
                       env=env)
    return p.returncode, (p.stdout + p.stderr).decode(errors="replace")


def main():
    cc = shlex.split(os.environ.get("CC", "cc"))
    flags = BASE_FLAGS + ["-I", str(ROOT)]
    env_base = {"PATH": "/usr/bin:/bin"}
    with tempfile.TemporaryDirectory(prefix="passt-prepatched-contract-") as temp:
        work = Path(temp)
        (work / "harness.c").write_text(HARNESS)
        util_seam = work / "util-seam.o"

        subprocess.run(cc + flags + [str(work / "harness.c"),
                                     str(ROOT / "util.c"),
                                     str(ROOT / "log.c"),
                                     "-o", str(work / "real")], check=True)
        # util.c is the only translation unit with the seam applied, so the
        # harness and log.c keep the real declarations.
        subprocess.run(cc + flags + ["-Dgetresuid=seam_getresuid",
                                     "-Dgetresgid=seam_getresgid", "-c",
                                     str(ROOT / "util.c"), "-o",
                                     str(util_seam)], check=True)
        subprocess.run(cc + flags + ["-DCREDS_SEAM", str(work / "harness.c"),
                                     str(util_seam), str(ROOT / "log.c"),
                                     "-o", str(work / "seam")], check=True)

        binaries = {"real": work / "real", "seam": work / "seam"}
        for label, case, which, creds, want in CASES:
            code, output = run(binaries[which], case, creds, env_base)
            if want == "pass":
                assert code == 0 and "prepatched=1 fd_prepatched=1" in output, \
                    (label, code, output)
                if case == "committed":
                    assert "fd_closed prepatched=1 fd_prepatched=1" in output, \
                        (label, output)
                print("contract", label, "PASS (accepted)", flush=True)
            elif want == "off":
                assert code == 0 and "prepatched=0 fd_prepatched=0" in output, \
                    (label, code, output)
                print("contract", label, "PASS (not applied)", flush=True)
            else:
                assert code == 1, (label, code, output)
                assert REFUSE[want] in output, (label, want, output)
                assert "prepatched=1" not in output, (label, output)
                print("contract", label, "PASS (refused:", REFUSE[want] + ")",
                      flush=True)


if __name__ == "__main__":
    main()
