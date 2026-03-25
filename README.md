# AAA Cloud-Native

A cloud-native telecom subscriber provisioning and AAA (Authentication, Authorization, Accounting) platform built for Kubernetes. The system assigns static IP addresses to SIM cards via RADIUS and provides a full provisioning API and management UI.

## Architecture

```
SMF/PGW/GGSN
   │  RADIUS UDP/1812
   ▼
aaa-radius-server (C++20)
   ├─ Stage 1: GET /lookup?imsi=&apn= ──► aaa-lookup-service (port 8081) ──► PostgreSQL read replica
   │                                          │
   │                        200 (IP) / 403 (suspended) / 404 (unknown)
   │
   └─ Stage 2 on 404: POST /first-connection ──► subscriber-profile-api (port 8080) ──► PostgreSQL primary
                                                          ▲
                                                  aaa-management-ui (React/TS)
```

## Plans

| # | Plan | Description |
|---|------|-------------|
| 01 | [Regression Test Client](aaa-regression-tester/plan-01-regression-test-client.md) | Python/pytest suite covering all REST endpoints, IP allocation scenarios, bulk ops, and first-connection flows. Runs as a Kubernetes Job with JUnit XML output and Prometheus metrics. ~8 min total runtime including 300K-row seed load. |
| 02 | [Database](charts/aaa-database/plan-02-database.md) | PostgreSQL 15+ schema with 9 tables modeling SIM profiles, IMSI ranges, IP pools, and APN mappings. Supports three IP resolution modes (`iccid`, `imsi`, `imsi_apn`) plus multi-IMSI per-slot routing. Hot-path lookup p99 <15ms via B-tree index; allocations use `SKIP LOCKED` to prevent races. |
| 03 | [AAA Lookup Service](aaa-lookup-service/plan-03-aaa-service.md) | Read-only FastAPI service (port 8081) serving the hot-path `GET /lookup?imsi=&apn=` at p99 <15ms. Returns static IP (200), suspended (403), or unknown (404). Scales 3–6 replicas per region, zero writes, connects only to a read replica. |
| 04 | [Provisioning API](subscriber-profile-api/plan-04-api.md) | Python/FastAPI service (port 8080) providing full CRUD for SIM profiles, IMSI ranges, IP pools, APNs, and bulk import jobs. Handles first-connection allocation (Stage 2 fallback), per-APN pool routing, and multi-IMSI SIM pre-provisioning. Bulk jobs run asynchronously in a thread pool. |
| 05 | [Management UI](aaa-management-ui/plan-05-ui.md) | React/TypeScript web app with an amber-on-navy theme for operators to manage SIM profiles, pools, range configs, and bulk imports. OAuth 2.0/OIDC auth with JWT stored in memory only. Deployed as a stateless Nginx container that proxies API calls. |
| 06 | [Migration](plan-06-migration.md) | 7-step procedure to migrate 8M rows from 7 regional MariaDB/Galera clusters to PostgreSQL: extract → transform → load (via staging + COPY) → 72h dual-write validation → 30-min cutover → ICCID enrichment → decommission. Total elapsed: 6–10 weeks. |
| 07 | [Umbrella Helm Chart & Dev Environment](charts/aaa-platform/plan-07-umbrella-dev-environment.md) | Helm umbrella chart orchestrating all six sub-charts across dev (k3d/WSL2), staging, and prod environments. Single `make bootstrap` stands up the full stack with Prometheus and Grafana. Local cluster runs on ~1.1 CPU / 2.2 GB RAM. |
| 08 | [RADIUS Server](aaa-radius-server/README.md) | Custom C++20 RADIUS server (UDP/1812) implementing RFC 2865 with a two-stage AAA flow. Thread pool of 16 workers handles ~1600 RPS at 5ms lookup latency. Maps 3GPP VSAs (IMSI, IMEISV, APN) and returns Access-Accept or Access-Reject with MD5 authenticator. |

## Technology Stack

| Layer | Technology |
|-------|-----------|
| RADIUS | C++20, libcurl, OpenSSL, spdlog |
| Lookup Service | Python 3.11, FastAPI, asyncpg |
| Provisioning API | Python 3.11, FastAPI, asyncpg, uvicorn |
| Management UI | React 18, TypeScript, Tailwind CSS, Vite |
| Database | PostgreSQL 15+, CloudNativePG, PgBouncer |
| Orchestration | Kubernetes, Helm 3, k3d |
| Observability | Prometheus, Grafana, kube-prometheus-stack |
| Testing | Python/pytest, Kubernetes Job |

## Quick Start

```bash
# Build all images
make build-all REGISTRY=<registry> TAG=dev

# Deploy full stack
make deploy

# Run regression tests
make test

# Connect to database (after port-forward-db)
psql "postgres://aaa_app:devpassword@localhost:5432/aaa"
```

See [DEPLOY.md](DEPLOY.md) for full deployment instructions.
