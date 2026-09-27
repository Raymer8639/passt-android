/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef PASST_ANDROID_COMPAT_H
#define PASST_ANDROID_COMPAT_H

#ifdef __ANDROID__
#include <inttypes.h>
#include <netinet/udp.h>

#ifndef MAXNS
#define MAXNS 3
#endif
#ifndef MAXDNSRCH
#define MAXDNSRCH 6
#endif
#ifndef _PATH_LOG
#define _PATH_LOG "/dev/log"
#endif

/* bionic's macro expects glibc's in6_addr union layout. */
#ifdef IN6_IS_ADDR_UNSPECIFIED
#undef IN6_IS_ADDR_UNSPECIFIED
#endif
#define IN6_IS_ADDR_UNSPECIFIED(a) \
    (memcmp((a), (const uint8_t[16]){ 0 }, 16) == 0)
#endif

#endif /* PASST_ANDROID_COMPAT_H */
