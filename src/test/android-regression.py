#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise production conf/address/fd APIs and ordered mapping with local stubs.

No namespaces, network access, or Android device are needed. The mapping stub
only records procfs writes; the fd tests use real socketpairs and close_range.
"""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include "conf.c"
#include <linux/close_range.h>
/* Unused cleanup state referenced by production fatal logging. */
struct ctx passt_ctx;
int pcap_fd = -1;
@ISOLATE_FDS@

int main(int argc, char **argv)
{
    struct ctx c = { 0 };
    const struct guest_addr *a;
    struct in6_addr a6;
    struct in_addr a4;
    int sv[2], extra;
    char number[32];
    char *fd_argv[] = { "passt", "-F", number, NULL, NULL };

    assert(argc == 2);
    if (!strcmp(argv[1], "conf")) {
        assert(conf_addr(&c, "192.0.2.2/24", 0));
        assert(conf_addr(&c, "fd00::2/80", 0));
        conf_ip4_local(&c);
        conf_ip6_local(&c);
        assert(inet_pton(AF_INET, "192.0.2.2", &a4) == 1);
        assert(inet_pton(AF_INET6, "fd00::2", &a6) == 1);
        assert(!memcmp(&c.ip4.addr_seen, &a4, sizeof(a4)));
        assert(!memcmp(&c.ip6.addr_seen, &a6, sizeof(a6)));
        a = fwd_get_addr(&c, AF_INET, true, CONF_ADDR_USER);
        assert(a && a->prefix_len == 120);
        a = fwd_get_addr(&c, AF_INET6, true, CONF_ADDR_USER);
        assert(a && a->prefix_len == 80);
        assert(c.ip4.addr_fixed && c.ip6.addr_fixed);
        assert(!conf_addr(&c, "192.0.2.3", conf_ip4_prefix("255.255.255.0") + 96));
        a = fwd_get_addr(&c, AF_INET, true, CONF_ADDR_USER);
        assert(a && a->prefix_len == 120);
        return 0;
    }
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, sv) == 0);
    extra = open("/dev/null", O_RDONLY);
    assert(extra > sv[1]);
    snprintf(number, sizeof(number), "%d", sv[1]);
    if (!strcmp(argv[1], "pass"))
        fd_argv[3] = "--pass-fds";
    isolate_fds(&c, fd_argv[3] ? 4 : 3, fd_argv);
    if (fd_argv[3]) {
        assert(c.pass_fds && c.fd_tap == sv[1]);
        assert(fcntl(extra, F_GETFD) >= 0);
    } else {
        assert(!c.pass_fds && c.fd_tap == 3);
        assert(fcntl(extra, F_GETFD) == -1 && errno == EBADF);
    }
    assert(setenv("PASST_ANDROID_NO_ISOLATION", "1", 1) == 0);
    assert(fd_prepatched(&c));
    return 0;
}
'''

MAP_SUPPORT = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
#include <limits.h>
#define snprintf_check(buf, len, ...) (snprintf(buf, len, __VA_ARGS__) >= (int)(len))
#define die_perror(...) assert(0)
static int calls, warnings, fail_mask;
static const char *names[] = { "uid_map", "setgroups", "gid_map" };
static int write_file(const char *path, const char *value)
{
    assert(calls < 3);
    assert(!strcmp(strrchr(path, '/') + 1, names[calls]));
    if (calls == 1) assert(!strcmp(value, "deny"));
    return (fail_mask & (1 << calls++)) ? -1 : 0;
}
#define warn(...) (++warnings)
'''


def main():
    cc = shlex.split(os.environ.get("CC", "cc"))
    flags = ["-D_GNU_SOURCE", "-D_XOPEN_SOURCE=700", "-DPAGE_SIZE=4096", '-DVERSION="regression"',
             "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror",
             "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
             "-fsanitize=undefined", "-fno-sanitize-recover=all", "-I", str(ROOT)]
    with tempfile.TemporaryDirectory(prefix="passt-android-regression-") as temp:
        work = Path(temp)
        source = work / "conf-fd.c"
        isolation = (ROOT / "isolation.c").read_text()
        start = isolation.index("void isolate_fds(")
        isolate_fds = isolation[start:isolation.index("\n}", start) + 2]
        source.write_text(HARNESS.replace("@ISOLATE_FDS@", isolate_fds))
        binary = work / "conf-fd"
        subprocess.run(cc + flags + [str(source)] +
                       [str(ROOT / f) for f in ("fwd.c", "parse.c", "ip.c", "log.c", "util.c")]
                       + ["-o", str(binary)], check=True)
        for mode in ("conf", "pass", "close"):
            subprocess.run([str(binary), mode], check=True)
            print("production address/fd API:", mode, "PASS", flush=True)
        util = (ROOT / "util.c").read_text()
        start = util.index("void make_ugid_map(")
        function = util[start:util.index("\n}", start) + 2]
        source.write_text(MAP_SUPPORT + function + r'''
int main(void)
{
    for (fail_mask = 0; fail_mask < 8; fail_mask++) {
        for (int pid = 0; pid <= 42; pid += 42) {
            calls = warnings = 0;
            make_ugid_map(pid, 1000, 1000);
            assert(calls == 3);
            assert(warnings == !!(fail_mask & 1) + !!(fail_mask & 4));
        }
    }
    return 0;
}
''')
        binary = work / "map"
        subprocess.run(cc + flags + [str(source), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
        print("production uid_map/setgroups/gid_map: 16 success/failure order cases PASS")


if __name__ == "__main__":
    main()
