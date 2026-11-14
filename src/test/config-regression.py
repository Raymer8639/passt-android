#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded startup probes of the built host binary, without guest networking."""
import os
from pathlib import Path
import socket
import subprocess
import sys

BINARY = str(Path(sys.argv[1]).resolve())
MSG = "--fd with IPv6 needs an explicit -a address"


def run(fd, opt_in, args):
    env = {"PATH": "/usr/bin:/bin"}
    if opt_in is not None:
        env["PASST_ANDROID_NO_ISOLATION"] = opt_in
    command = [BINARY, "-f", "-d", "-t", "none", "-u", "none"]
    if fd is not None:
        command += ["-F", str(fd)]
    try:
        p = subprocess.run(command + args, pass_fds=() if fd is None else (fd,),
                           capture_output=True, timeout=2, env=env)
        return p.returncode, (p.stdout + p.stderr).decode(errors="replace")
    except subprocess.TimeoutExpired as exc:
        return 124, ((exc.stdout or b"") + (exc.stderr or b"")).decode(errors="replace")


def check(label, fd, opt_in, want_local):
    code, output = run(fd, opt_in, ["-6"])
    assert (MSG in output) == want_local, (label, code, output)
    if want_local:
        assert code not in (0, 124), (label, code, output)
    else:
        assert "Prepatched socket endpoint" not in output, (label, code, output)
        assert code == 124 or (code > 0 and any(x in output for x in (
            "Failed to", "Couldn't", "Can't", "Operation not permitted",
            "Permission denied", "Invalid argument"))), (label, code, output)
    print(label, "PASS exit=" + str(code), flush=True)


def main():
    a, b = socket.socketpair()
    try:
        for opt in ("1", "yes"):
            check("connected + " + opt, a.fileno(), opt, True)
        for opt in (None, "0", "true"):
            check("connected + " + str(opt), a.fileno(), opt, False)
        code, output = run(a.fileno(), "1", ["-6", "-a", "192.0.2.2/24"])
        assert MSG in output and code not in (0, 124), (code, output)
        print("IPv6 with IPv4-only address PASS refused", flush=True)
        for label, args, required in (
            ("IPv4 CIDR", ["-4", "-a", "192.0.2.2/24", "-g", "192.0.2.1", "-D", "192.0.2.53"],
             ("assign: 192.0.2.2", "mask: 255.255.255.0", "router: 192.0.2.1", "192.0.2.53")),
            ("IPv4 netmask", ["-4", "-a", "192.0.2.2", "-n", "255.255.255.0", "-g", "192.0.2.1"],
             ("assign: 192.0.2.2", "mask: 255.255.255.0")),
            ("IPv6 explicit", ["-6", "-a", "fd00::2/80", "-g", "fe80::1", "-D", "fd00::53"],
             ("assign: fd00::2", "router: fe80::1", "fd00::53")),
            ("dual stack", ["-a", "192.0.2.2/24", "-a", "fd00::2/64", "-g", "192.0.2.1", "-g", "fe80::1"],
             ("assign: 192.0.2.2", "assign: fd00::2", "router: fe80::1")),
        ):
            code, output = run(a.fileno(), "1", args)
            assert code == 124, (label, code, output)
            assert "skipping namespace isolation" in output, (label, output)
            assert "Failed to get netlink socket" not in output, (label, output)
            for text in required:
                assert text in output, (label, text, output)
            print(label, "PASS configured and entered event loop", flush=True)
    finally:
        a.close(); b.close()
    r, w = os.pipe()
    try:
        check("pipe + opt-in", r, "1", False)
    finally:
        os.close(r); os.close(w)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        check("unconnected + opt-in", s.fileno(), "1", False)
    check("no fd + opt-in", None, "1", False)


if __name__ == "__main__":
    main()
