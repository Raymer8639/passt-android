#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Compile production TCP code with isolated boundary stubs, without namespaces.

The MSS macros, complete buffer sender, and complete half-closed handler branch
are read from the selected source tree, not reimplemented in this test.  The
socket read is real; tap output, flow bookkeeping and scheduling are instrumented.
This is a unit regression, not a packet/network-namespace integration test.
Use --source /path/to/old/src to demonstrate that an unfixed tree fails.
"""
import argparse
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile


def macro(source, name):
    match = re.search(r"^#define[ \t]+" + name + r"(?:\([^\n]*?\))?[ \t]+(?:[^\n]*\\\n)*[^\n]*", source, re.M)
    if not match:
        raise ValueError("missing macro " + name)
    return match[0] + "\n"


def block(source, start):
    begin = source.index(start)
    brace = source.index("{", begin)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[begin:end]


SUPPORT = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <time.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/uio.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#define MAX(a,b) ((a) > (b) ? (a) : (b))
#define BIT(n) (1U << (n))
#define DIV_ROUND_UP(n,d) (((n) + (d) - 1) / (d))
#define TCP_FRAMES 32
#define TCP_FRAMES_MEM 64
#define DISCARD_IOV_NUM 1
struct ctx { int unused; };
struct tcp_tap_conn {
    unsigned int tap_mss:14;
    uint32_t wnd_from_tap, ws_from_tap, seq_to_tap, seq_ack_from_tap;
    uint32_t seq_ack_to_tap, seq_from_tap;
    int sock, events, flags;
};
static struct { char data[65536]; } tcp_payload[TCP_FRAMES_MEM];
static struct iovec iov_sock[TCP_FRAMES + DISCARD_IOV_NUM];
static unsigned int tcp_payload_used;
static bool peek_offset_cap = true;
static int emitted, reset_count, rewinds, socket_sends;
static size_t emitted_bytes, largest, advertised;
static uint32_t next_seq;
static size_t tcp_packet_data_len(const struct tcphdr *th, size_t len)
{ return len - th->doff * 4U; }
#define flow_dbg(...) ((void)0)
#define flow_trace(...) ((void)0)
static void tcp_rst(const struct ctx *c, struct tcp_tap_conn *conn,
                    const struct timespec *now)
{ (void)c; (void)conn; (void)now; reset_count++; }
static void conn_flag(const struct ctx *c, struct tcp_tap_conn *conn,
                      int flag, const struct timespec *now)
{ (void)c; (void)now; if (flag < 0) conn->flags &= flag; else conn->flags |= flag; }
static void conn_event(const struct ctx *c, struct tcp_tap_conn *conn,
                       int event, const struct timespec *now)
{ (void)c; (void)now; if (!event) conn->events = 0; else conn->events |= event; }
static int tcp_prepare_iov(struct msghdr *mh, struct iovec *iov,
                           uint32_t sent, int count)
{ assert(!sent); mh->msg_iov = iov + DISCARD_IOV_NUM; mh->msg_iovlen = count; return 0; }
static void tcp_payload_flush(const struct ctx *c, const struct timespec *now)
{ (void)c; (void)now; tcp_payload_used = 0; }
static int tcp_buf_send_flag(const struct ctx *c, struct tcp_tap_conn *conn,
                              int flags, const struct timespec *now)
{ (void)c; (void)flags; (void)now; conn->seq_to_tap++; return 0; }
static void tcp_update_seqack_wnd(const struct ctx *c, struct tcp_tap_conn *conn,
                                  bool force, void *info, const struct timespec *now)
{ (void)c; (void)conn; (void)force; (void)info; (void)now; }
static void tcp_data_to_tap(const struct ctx *c, struct tcp_tap_conn *conn,
                            int len, int csum, uint32_t seq, bool push,
                            const struct timespec *now)
{
    (void)c; (void)csum; (void)push; (void)now;
    assert(len > 0 && (size_t)len <= advertised);
    assert(seq == next_seq);
    for (int j = 0; j < len; j++) assert(tcp_payload[tcp_payload_used].data[j] == 'x');
    next_seq += len; conn->seq_to_tap = next_seq;
    emitted++; emitted_bytes += len;
    if ((size_t)len > largest) largest = len;
    tcp_payload_used++;
}
static int tcp_sock_consume(struct tcp_tap_conn *conn, uint32_t ack)
{ (void)conn; (void)ack; return 0; }
static void tcp_update_seqack_from_tap(const struct ctx *c, struct tcp_tap_conn *conn,
                                      uint32_t ack, const struct timespec *now)
{ (void)c; (void)now; conn->seq_ack_from_tap = ack; }
static int tcp_rewind_seq(const struct ctx *c, struct tcp_tap_conn *conn,
                           const struct timespec *now)
{
    (void)c; (void)now; rewinds++;
    conn->seq_to_tap = conn->seq_ack_from_tap;
    conn->events &= ~TAP_FIN_SENT;
    return 0;
}
static bool tcp_tap_window_update(const struct ctx *c, struct tcp_tap_conn *conn,
                                  uint16_t window, const struct timespec *now)
{ (void)c; (void)now; bool changed = window != conn->wnd_from_tap;
  conn->wnd_from_tap = window; return changed; }
static void tcp_data_from_sock(const struct ctx *c, struct tcp_tap_conn *conn,
                                const struct timespec *now)
{ (void)c; (void)now; socket_sends++; conn->seq_to_tap++; conn->events |= TAP_FIN_SENT; }
'''
TESTS = r'''
static void test_mss(void)
{
    struct ctx c = {0}; struct timespec now = {0};
    for (unsigned int mss = 0; mss <= 65535; mss++) {
        struct tcp_tap_conn conn = {0};
        MSS_SET((&conn), mss);
        unsigned int got = MSS_GET((&conn));
        assert(got <= mss);
        assert(mss == 0 ? got == 0 : got > 0);
    }
    const unsigned int samples[] = {0,1,2,3,4,5,7,8,9,536,1460,65535};
    for (size_t i = 0; i < sizeof(samples)/sizeof(samples[0]); i++) {
        unsigned int mss = samples[i]; int fds[2]; char data[97];
        assert(socketpair(AF_UNIX, SOCK_STREAM, 0, fds) == 0);
        memset(data, 'x', sizeof(data));
        assert(write(fds[0], data, sizeof(data)) == sizeof(data));
        struct tcp_tap_conn conn = {.sock=fds[1], .wnd_from_tap=97, .seq_to_tap=100};
        MSS_SET((&conn), mss);
        advertised=mss; emitted=0; emitted_bytes=0; largest=0; next_seq=100;
        tcp_payload_used=0; reset_count=0;
        assert(tcp_buf_data_from_sock(&c, &conn, 0, &now) == 0);
        assert(!reset_count);
        if (!mss) { assert(!emitted && conn.seq_to_tap == 100); }
        else {
            unsigned int effective = MSS_GET((&conn));
            size_t expected = effective * TCP_FRAMES;
            if (expected > sizeof(data)) expected = sizeof(data);
            assert(emitted > 0 && emitted_bytes == expected && largest <= mss);
            assert(conn.seq_to_tap == 100 + expected);
        }
        /* MSG_PEEK must leave all data queued, including the zero-MSS case. */
        assert(recv(fds[1], data, sizeof(data), MSG_DONTWAIT) == sizeof(data));
        close(fds[0]); close(fds[1]);
    }
    puts("PASS MSS: all 65536 wire values; real socket buffer segmentation and zero-MSS no-send");
}
static void fin_case(uint32_t ack, uint32_t outstanding, bool fin_sent,
                     bool ack_flag, bool fin_flag, int window_delta, int ack_delta,
                     int want_rewind)
{
    struct ctx context = {0}; const struct ctx *c=&context;
    struct timespec time = {0}; const struct timespec *now=&time;
    struct tcp_tap_conn connection = {.seq_ack_from_tap=ack,
        .seq_to_tap=ack+outstanding, .wnd_from_tap=4096,
        .events=TAP_FIN_RCVD | (fin_sent ? TAP_FIN_SENT : 0)};
    struct tcp_tap_conn *conn=&connection;
    struct tcphdr header = {.ack=ack_flag, .fin=fin_flag, .doff=5,
        .ack_seq=htonl(ack+ack_delta), .window=htons(4096+window_delta)};
    const struct tcphdr *th=&header;
    rewinds=0; socket_sends=0;
    assert(close_wait(c, conn, th, sizeof(header), now) == 1);
    assert(rewinds == want_rewind);
    if (want_rewind) assert(socket_sends == 1);
    if (!want_rewind && !window_delta) assert(socket_sends == 0);
}
static void test_fin(void)
{
    for (int i=0; i<10000; i++) fin_case(100,1,true,true,false,0,0,0);
    fin_case(UINT32_MAX,1,true,true,false,0,0,0); /* sequence wrap */
    fin_case(100,2,true,true,false,0,0,1); /* data then FIN */
    fin_case(100,1,false,true,false,0,0,1); /* one data byte */
    fin_case(100,20,false,true,false,0,0,1);
    fin_case(100,1,true,true,false,1,0,0); /* changed window */
    fin_case(100,2,true,true,false,0,1,0); /* ACK progress */
    fin_case(100,2,true,false,false,0,0,0);
    fin_case(100,2,true,true,true,0,0,0);
    puts("PASS FIN: repeated/wrapped FIN-only dupACK suppressed; data fast retransmit retained; ACK/window controls");
}
int main(int argc, char **argv)
{ assert(argc == 2); if (!strcmp(argv[1], "mss")) test_mss(); else test_fin(); return 0; }
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    header = (args.source / "tcp_conn.h").read_text()
    buf = (args.source / "tcp_buf.c").read_text()
    tcp = (args.source / "tcp.c").read_text()
    names = ["TCP_MSS_BITS", "MSS_SET", "MSS_GET", "CLOSED", "SOCK_FIN_RCVD",
             "TAP_FIN_RCVD", "TAP_FIN_SENT", "TAP_FIN_ACKED", "STALLED",
             "ACK_FROM_TAP_DUE", "ACK_FROM_TAP_BLOCKS"]
    macros = "".join(macro(header, name) for name in names)
    internal = (args.source / "tcp_internal.h").read_text()
    macros += macro(internal, "FIN") + macro(internal, "ACK")
    sender = block(buf, "int tcp_buf_data_from_sock(")
    closing = block(tcp[tcp.index("int tcp_tap_handler("):],
                    "if (conn->events & TAP_FIN_RCVD) {")
    wrapper = ("static int close_wait(const struct ctx *c, struct tcp_tap_conn *conn, "
               "const struct tcphdr *th, size_t l4len, const struct timespec *now) {\n"
               + closing + "\nreturn 0;\n}\n")
    with tempfile.TemporaryDirectory(prefix="passt-tcp-regression-") as temp:
        source = Path(temp) / "regression.c"
        binary = Path(temp) / "regression"
        source.write_text(macros + SUPPORT + sender + "\n" + wrapper + TESTS)
        subprocess.run(shlex.split(os.environ.get("CC", "cc")) + [
            "-D_DEFAULT_SOURCE", "-std=c11", "-Wall", "-Wextra", "-Werror",
            "-O1", "-g", "-fsanitize=undefined", "-fno-sanitize-recover=all",
            str(source), "-o", str(binary)], check=True)
        failures = 0
        for case in ["mss", "fin"]:
            result = subprocess.run([str(binary), case], check=False)
            failures += result.returncode != 0
        raise SystemExit(bool(failures))


if __name__ == "__main__":
    main()
