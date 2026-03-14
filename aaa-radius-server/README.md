# aaa-radius-server

Lightweight C++ RADIUS authentication server. Receives `Access-Request` packets on UDP/1812, performs two-stage AAA, and returns `Access-Accept` (with `Framed-IP-Address`) or `Access-Reject`.

## Architecture

```
NAS / PGW/ SMF/ GGSN  (UDP 1812)
      │
      ▼
aaa-radius-server
  ├── recvfrom loop  (main thread)
  └── thread pool   (WORKER_THREADS workers, each owns a CURL handle)
        │
        ├─ Stage 1 — GET /lookup?imsi={imsi}&apn={apn}
        │     200  → Access-Accept + Framed-IP-Address
        │     403  → Access-Reject  (subscriber suspended)
        │     404  → Stage 2 ↓
        │
        └─ Stage 2 — POST /v1/first-connection  {imsi, apn, imei}
              200  → Access-Accept + Framed-IP-Address
              404/503 → Access-Reject  (no range config or pool exhausted)
```

## RADIUS packet mapping (from pcap analysis)

| RADIUS attribute | Source | Used for |
|---|---|---|
| VSA vendor=10415 type=1 (3GPP-IMSI) | Access-Request | IMSI (preferred) |
| User-Name (attr 1) | Access-Request | IMSI fallback if VSA absent |
| Called-Station-Id (attr 30) | Access-Request | APN |
| Calling-Station-Id (attr 31) | Access-Request | MSISDN (logged only) |
| VSA vendor=10415 type=20 (3GPP-IMEISV) | Access-Request | IMEI (Stage 2 only) |
| Framed-IP-Address (attr 8) | Access-Accept | Allocated static IP |

Access-Accept total length is 26 bytes (20-byte header + 6-byte Framed-IP attr).
Response authenticator = `MD5(code | id | length | reqAuth | attrs | secret)`.

## Configuration (environment variables)

| Variable | Default | Description |
|---|---|---|
| `RADIUS_PORT` | `1812` | UDP port to listen on |
| `RADIUS_SECRET` | `testing123` | Shared secret with NAS clients (**required in prod**) |
| `LOOKUP_URL` | `http://aaa-lookup-service:8081` | aaa-lookup-service base URL |
| `PROVISIONING_URL` | `http://subscriber-profile-api:8080` | subscriber-profile-api base URL |
| `WORKER_THREADS` | `8` | Thread pool size (see sizing section below) |
| `LOG_LEVEL` | `info` | `trace` \| `debug` \| `info` \| `warn` \| `error` |

## Build

```bash
# Build image
make build-radius-server REGISTRY=k3d-aaa-registry.localhost:5111 TAG=dev

# Or as part of the full platform
make build-all
```

Local build (without Docker):
```bash
cd aaa-radius-server
cmake -S . -B build \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_TOOLCHAIN_FILE=$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake
cmake --build build -j$(nproc)
```

## Capacity sizing — 1000 RPS, 99.9% lookup hit rate

> **Scenario**: 1000 Access-Request/s, 999/s resolved by Stage 1 (GET /lookup → 200),
> 1/s falls through to Stage 2 (POST /first-connection).

### Worker threads — the critical parameter

Workers block on the HTTP round-trip for the full duration of each request.
Capacity follows **Little's Law**:

```
Required workers = arrival rate × avg HTTP round-trip latency
```

| Lookup service p50 | Workers needed for 1000 RPS | At default 8 workers |
|---|---|---|
| 3 ms | 3 | ✅ 2,667 RPS capacity |
| 5 ms | 5 | ✅ 1,600 RPS capacity |
| 8 ms | 8 | ⚠️ exactly at limit, zero headroom |
| 10 ms | 10 | ❌ 800 RPS capacity (drops requests) |

The lookup service SLA is p99 < 15 ms, so p50 is typically 3–7 ms in-cluster.
However, 8 workers leaves no headroom if p50 drifts to 8 ms (DB replica lag spike, cold cache, etc.).

**Recommended: `WORKER_THREADS: 16`** — sustains 1000 RPS even if p50 reaches 16 ms, and provides 3× headroom at 5 ms.

### CPU

Workers spend most of their time **sleeping on I/O** (waiting for the HTTP response).
Actual CPU work per request:

| Operation | Time |
|---|---|
| UDP `recvfrom` + `sendto` syscalls | ~2 µs |
| RADIUS packet parse (memcpy, strings) | ~4 µs |
| libcurl overhead (poll, HTTP frame parsing) | ~15 µs |
| nlohmann::json parse | ~4 µs |
| OpenSSL MD5 (response authenticator) | ~2 µs |
| Thread queue mutex ops | ~3 µs |
| spdlog format + write | ~8 µs |
| **Total compute per request** | **~38 µs** |

```
CPU at 1000 RPS = 1000 req/s × 38 µs = 38 ms/s ≈ 0.04 cores
```

With 2× safety margin: **`requests: 100m`, `limits: 250m`** per pod.

### RAM

| Component | RSS |
|---|---|
| Binary + shared libs (libcurl, libssl3, libc) | ~12–15 MB |
| 16 thread stacks (virtual 8 MB each; actual RSS ~80 KB each) | ~1.3 MB |
| libcurl: 16 CURL handles × ~40 KB state | ~640 KB |
| libcurl: DNS cache + connection state | ~200 KB |
| In-flight request buffers (16 × ~600 bytes) | ~10 KB |
| Work queue (typically empty at steady-state 1000 RPS) | ~50 KB |
| spdlog ring buffer + formatter | ~1 MB |
| **Total RSS** | **~15–18 MB** |

**`requests: 32Mi`, `limits: 64Mi`** per pod.

### Recommended resource values for 1000 RPS

Update `charts/aaa-radius-server/values.yaml`:

```yaml
workerThreads: 16      # default 8 is insufficient if lookup p50 > 8 ms

resources:
  requests:
    cpu: "100m"        # compute is I/O-bound; actual usage ~40m at 1000 RPS
    memory: "32Mi"     # actual RSS ~15-18 MB
  limits:
    cpu: "250m"
    memory: "64Mi"
```

### Full picture — 2-replica deployment

| | Per pod | Total (2 pods) |
|---|---|---|
| CPU request | 100m | **200m** |
| CPU limit | 250m | 500m |
| RAM request | 32Mi | **64Mi** |
| RAM limit | 64Mi | 128Mi |
| Worker threads | 16 | 32 effective |
| Throughput capacity | ~1,600 RPS (at 10 ms p50) | ~3,200 RPS combined |

> The **aaa-lookup-service** (3 replicas × 500m CPU, 512Mi RAM) is the heavier
> component — it runs the DB query on every request. The radius server is cheap
> because it is a thin protocol-translation layer, mostly blocked on network I/O.
