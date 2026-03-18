## HTTP/2 vs HTTP/1.1 — Capacity Impact Analysis

Based on the three plans, here's the breakdown by component:

---

### `aaa-radius-server` (plan-08) — The Critical Path

This is where HTTP/2 has the **most nuanced impact**, but the current architecture limits the benefit.

**Current model (HTTP/1.1):**
- Each worker thread owns one blocking `CURL*` handle → one in-flight request at a time
- Capacity is entirely governed by Little's Law: `workers = rate × latency`
- 16 workers × (1000ms / 5ms p50) = **3,200 RPS capacity**

**With HTTP/2 + current blocking design:**
HTTP/2 multiplexing is **not exploited** — each worker still blocks on one request. The benefit is limited to:

| Factor | HTTP/1.1 | HTTP/2 | Delta |
|---|---|---|---|
| TCP connections to `aaa-lookup-service` | 16 (one/worker) | 1 shared | −15 connections/pod |
| Header size per `GET /lookup` | ~400 bytes | ~80 bytes (HPACK) | −320 bytes |
| Latency reduction | baseline | ~0.5–1 ms | marginal |

If latency drops 1 ms (5ms→4ms p50), the capacity table from plan-08 becomes:

| Lookup p50 | Workers @ HTTP/1.1 | Workers @ HTTP/2 |
|---|---|---|
| 4 ms | 5 | 4 |
| 5 ms | 5 | 5 (no change if savings <1ms) |
| 8 ms | 8 | 7 |

**`WORKER_THREADS: 16` recommendation is unchanged** — the DB query dominates latency, not the HTTP framing layer.

**The real HTTP/2 gain would require a design change:** If `HttpClient.cpp` switches from per-thread blocking `CURL*` to a shared `curl_multi` async handle, you could have 4 threads × 4 multiplexed streams = same 16 in-flight requests, cutting RAM from ~15 MB to ~8 MB and eliminating 12 thread stacks.

---

### `aaa-lookup-service` (plan-03) — No Meaningful Impact

The bottleneck is the **DB connection pool (5–10 connections to read replica)**, not HTTP:
- HTTP/2 doesn't increase DB concurrency
- The 3–6 replicas × 5–10 DB connections remain the scaling lever
- Drogon (C++) natively supports HTTP/2, so enabling it is free, but it won't move the p99 < 15 ms SLA needle

---

### `subscriber-profile-api` (plan-04) — Negligible for AAA Path

- **Stage 2 (first-connection)** fires only ~0.1% of the time at 99.9% hit rate — at 1000 RPS that's ~1 req/s. HTTP/2 overhead savings here are irrelevant.
- **Provisioning CRUD** is operator-driven low-volume — HTTP/2 connection reuse helps slightly for concurrent BSS/OSS tooling but not materially.
- **Bulk jobs** are async (202 Accepted) — HTTP/2 makes no difference.
- FastAPI+uvicorn requires `hypercorn` or explicit H2 config for true HTTP/2 — not automatic.

---

### Summary

| Component | Bottleneck | HTTP/2 Impact |
|---|---|---|
| `aaa-radius-server` | Worker thread count (Little's Law) | Marginal latency reduction; **no change to `WORKER_THREADS: 16`** unless async multi-handle refactor is done |
| `aaa-lookup-service` | PostgreSQL read replica pool (5–10 conns) | **None** — DB is the constraint |
| `subscriber-profile-api` | DB write transaction (~18ms) for Stage 2 | **None** on AAA path; minor for concurrent provisioning |

**Bottom line:** HTTP/2 provides mild bandwidth and connection-count savings in-cluster, but capacity numbers in plan-08 don't change because the system is I/O-bound on the DB, not on HTTP framing. The only scenario where HTTP/2 materially changes capacity is if `aaa-radius-server` is refactored to use async multiplexed curl handles — which would halve thread count and RAM while maintaining the same RPS.