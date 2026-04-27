#!/usr/bin/env python3
"""
RADIUS Load Generator v7
- Sender thread: ONLY sends, never blocks on reply
- Receiver thread: ONLY recvfrom, updates stats
- Reaper thread: handles timeouts
- Token bucket rate control
"""

import socket
import struct
import os
import time
import argparse
import threading
import collections

# ── Config ────────────────────────────────────────────────────────────────────
RADIUS_SERVER  = "192.168.96.249"
# RADIUS_SERVER  = "192.168.114.170"
RADIUS_PORT    = 1812
SHARED_SECRET  = b"testing123"
TOTAL_REQUESTS = 100_000
TARGET_RPS     = 2_000
REPLY_TIMEOUT  = 0.3
IMSI_BASE      = 268010000000001

# Fixed AVP values from pcap
NAS_IP         = "0.0.0.0"
FRAMED_IP      = "10.128.47.67"
CALLED_STATION = b"internet-radius-auth"
SGSN_ADDR      = "192.168.114.170"
GGSN_ADDR      = "192.168.96.231"
QOS_PROFILE    = b"08-0508000C3500000C3500"

# ── Stats ─────────────────────────────────────────────────────────────────────
stats = dict(sent=0, accept=0, reject=0, noreply=0)

# ── RADIUS packet builder ─────────────────────────────────────────────────────
def ip2b(ip):  return socket.inet_aton(ip)
def u32(v):    return struct.pack("!I", v)
def u8(v):     return struct.pack("B", v)

def avp(t, v):
    return struct.pack("BB", t, 2 + len(v)) + v

def vsa(vendor, t, v):
    return avp(26, struct.pack("!I", vendor) + struct.pack("BB", t, 2 + len(v)) + v)

def build_request(pkt_id: int, imsi: int, seq: int) -> bytes:
    attrs  = avp(4,  ip2b(NAS_IP))
    attrs += avp(6,  u32(2))
    attrs += avp(7,  u32(7))
    attrs += avp(8,  ip2b(FRAMED_IP))
    attrs += avp(30, CALLED_STATION)
    attrs += avp(44, f"{seq:016X}".encode())
    attrs += avp(61, u32(15))
    attrs += vsa(10415, 1,  str(imsi).encode())
    attrs += vsa(10415, 2,  u32(3821763459))
    attrs += vsa(10415, 3,  u32(0))
    attrs += vsa(10415, 5,  QOS_PROFILE)
    attrs += vsa(10415, 6,  ip2b(SGSN_ADDR))
    attrs += vsa(10415, 7,  ip2b(GGSN_ADDR))
    attrs += vsa(10415, 10, u8(5))
    attrs += vsa(10415, 12, u8(1))
    attrs += vsa(10415, 18, b"000000")
    attrs += vsa(10415, 21, u8(6))
    attrs += vsa(10415, 23, b"\x00\x00")
    attrs += vsa(10415, 27, u8(0))

    length = 20 + len(attrs)
    auth   = os.urandom(16)
    return struct.pack("!BBH16s", 1, pkt_id, length, auth) + attrs

# ── Shared state ──────────────────────────────────────────────────────────────
class SharedState:
    def __init__(self):
        self.lock     = threading.Lock()
        self.id_sem   = threading.Semaphore(254)  # max 254 in-flight
        self.id_pool  = collections.deque(range(1, 255))
        # pkt_id -> sent_timestamp (for timeout detection)
        self.pending  = {}

    def acquire_id(self) -> int:
        self.id_sem.acquire()
        with self.lock:
            return self.id_pool.popleft()

    def release_id(self, pkt_id: int):
        with self.lock:
            self.id_pool.append(pkt_id)
            self.pending.pop(pkt_id, None)
        self.id_sem.release()

    def register(self, pkt_id: int):
        with self.lock:
            self.pending[pkt_id] = time.monotonic()

    def resolve(self, pkt_id: int) -> bool:
        """Returns True if was pending (not already timed out)."""
        with self.lock:
            return self.pending.pop(pkt_id, None) is not None

    def expired(self, timeout: float) -> list:
        """Returns list of pkt_ids that have timed out."""
        now = time.monotonic()
        with self.lock:
            return [pid for pid, t in self.pending.items()
                    if now - t > timeout]

# ── Token bucket ──────────────────────────────────────────────────────────────
class TokenBucket:
    def __init__(self, rate):
        self.rate   = rate
        self.tokens = 1.0  # start with 1 to avoid burst on first second
        self.last   = time.monotonic()

    def acquire(self):
        while True:
            now          = time.monotonic()
            self.tokens += (now - self.last) * self.rate
            self.last    = now
            if self.tokens > self.rate:
                self.tokens = self.rate
            if self.tokens >= 1:
                self.tokens -= 1
                return
            time.sleep(0.0001)

# ── Threads ───────────────────────────────────────────────────────────────────
def sender_thread(sock, state, args, done):
    """Only sends — never waits for reply."""
    bucket = TokenBucket(args.rps)
    target = (args.server, args.port)

    for i in range(args.total):
        bucket.acquire()
        imsi   = args.imsi + i
        pkt_id = state.acquire_id()          # blocks only if 254 in-flight
        pkt    = build_request(pkt_id, imsi, i)
        state.register(pkt_id)
        sock.sendto(pkt, target)
        stats["sent"] += 1

    done.set()

def receiver_thread(sock, state, done):
    """Only receives — uses select so GIL is released while waiting."""
    import select
    while not done.is_set() or state.pending:
        ready, _, _ = select.select([sock], [], [], 0.1)
        if not ready:
            continue
        try:
            data, _ = sock.recvfrom(4096)
            if len(data) < 20:
                continue
            code, pkt_id = data[0], data[1]
            if state.resolve(pkt_id):
                if code == 2:    stats["accept"] += 1
                elif code == 3:  stats["reject"] += 1
                else:            stats["noreply"] += 1
            state.release_id(pkt_id)
        except BlockingIOError:
            continue

def reaper_thread(state, timeout, done):
    """Cleans up timed-out requests aggressively."""
    while not done.is_set() or state.pending:
        time.sleep(0.01)    # check every 10ms
        for pkt_id in state.expired(timeout):
            stats["noreply"] += 1
            state.release_id(pkt_id)

def printer_thread(total, done):
    t0, last = time.monotonic(), 0
    while not done.is_set():
        time.sleep(1.0)
        cur = stats["sent"]
        print(f"[{time.monotonic()-t0:6.1f}s] sent={cur:>7,}  rps={cur-last:>5,}  "
              f"accept={stats['accept']:>6,}  reject={stats['reject']:>4,}  "
              f"noreply={stats['noreply']:>5,}  progress={cur/total*100:5.1f}%")
        last = cur

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="RADIUS 3GPP load generator v7")
    parser.add_argument("--server",        default=RADIUS_SERVER)
    parser.add_argument("--port",          type=int,   default=RADIUS_PORT)
    parser.add_argument("--secret",        default=SHARED_SECRET.decode())
    parser.add_argument("--total",         type=int,   default=TOTAL_REQUESTS)
    parser.add_argument("--rps",           type=int,   default=TARGET_RPS)
    parser.add_argument("--imsi",          type=int,   default=IMSI_BASE)
    parser.add_argument("--reply-timeout", type=float, default=REPLY_TIMEOUT)
    args = parser.parse_args()

    print(f"RADIUS load generator v7")
    print(f"  Target : {args.server}:{args.port}")
    print(f"  Total  : {args.total:,}  Rate: {args.rps:,} req/s")
    print(f"  IMSI   : {args.imsi} → {args.imsi + args.total - 1}\n")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)                              # non-blocking — no GIL hold

    print(f"  Port   : {sock.getsockname()}\n")

    state = SharedState()
    done  = threading.Event()

    threads = [
        threading.Thread(target=receiver_thread, args=(sock, state, done),               daemon=True),
        threading.Thread(target=reaper_thread,   args=(state, args.reply_timeout, done), daemon=True),
        threading.Thread(target=printer_thread,  args=(args.total, done),                daemon=True),
        threading.Thread(target=sender_thread,   args=(sock, state, args, done)),
    ]

    t0 = time.monotonic()
    for t in threads:
        t.start()
    threads[-1].join()

    while state.pending:
        time.sleep(0.1)

    elapsed = time.monotonic() - t0
    print(f"\nDone in {elapsed:.1f}s — avg {stats['sent']/elapsed:.0f} req/s")
    print(f"Accept={stats['accept']:,}  Reject={stats['reject']:,}  NoReply={stats['noreply']:,}")
    sock.close()

if __name__ == "__main__":
    main()
