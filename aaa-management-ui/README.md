# AAA Management UI

Browser-based management console for telecom operators to manage SIM profiles, IP pools, routing domains, range configurations, and bulk provisioning jobs. Communicates exclusively with the `subscriber-profile-api` REST backend — no direct database access.

**Stack:** React 18 · TypeScript 5 · Vite 5 · Tailwind CSS 3 · Zustand · Axios  
**Runtime:** Nginx 1.27 (static assets + `/v1/` proxy)  
**Auth:** OAuth 2.0 / OIDC — JWT stored in memory only (never persisted)

---

## Pages

| Route | Page | Purpose |
|-------|------|---------|
| `/dashboard` | Dashboard | Active SIM count, pool utilization, recent bulk jobs, quick links |
| `/devices/*` | SIMs | List/search SIM profiles; detail with IMSI/APN manager; create; bulk import |
| `/pools/*` | IP Pools | Pool CRUD with utilization stats |
| `/routing-domains/*` | Routing Domains | Domain CRUD; allowed prefixes; free-CIDR suggestion tool |
| `/range-configs/*` | IMSI Range Configs | IMSI range CRUD; APN pool mapping; provisioning mode |
| `/iccid-range-configs/*` | ICCID Range Configs | Multi-IMSI SIM ranges; IMSI slot manager |
| `/bulk-jobs/*` | Bulk Jobs | Job status, progress tracking, error report download |
| `/sim-profile-types` | SIM Profile Types | Reference: 4 profile type comparison with diagrams |
| `/documentation` | Documentation | Data model, DB schema, first-connection flow |

---

## Local Development

```bash
npm install
npm run dev        # Vite dev server on http://localhost:5173
                   # /v1/ proxied to http://localhost:8080
```

**Required env vars for local dev (`.env.local`):**

```env
VITE_API_BASE_URL=http://localhost:8080/v1
VITE_OIDC_AUTHORITY=https://your-keycloak/realms/your-realm
VITE_OIDC_CLIENT_ID=aaa-management-ui
```

---

## Build

```bash
npm run build      # TypeScript check + Vite build → dist/
npm run preview    # Preview production build locally
```

---

## Docker

```bash
docker build -t aaa-management-ui:latest .
docker run -p 8080:80 aaa-management-ui:latest
```

Multi-stage build: Node 20-alpine compiles the React app, Nginx 1.27-alpine serves `dist/`. The Nginx config:
- Routes all paths to `index.html` (SPA)
- Proxies `/v1/` → `http://subscriber-profile-api:8080/v1/` (timeouts: 10s connect, 30s send, 120s read)
- Health check at `GET /health` → `200 ok`

---

## Configuration

At runtime, Nginx injects `config.js` (from a Kubernetes ConfigMap) into the HTML shell, setting `window.APP_CONFIG`. For local dev, Vite env vars are used instead.

| Key | `window.APP_CONFIG` field | Vite env var | Default | Purpose |
|-----|--------------------------|--------------|---------|---------|
| API base URL | `apiBaseUrl` | `VITE_API_BASE_URL` | `/v1` | Backend API prefix |
| OIDC authority | `oidcAuthority` | `VITE_OIDC_AUTHORITY` | — | OIDC provider URL |
| OIDC client ID | `oidcClientId` | `VITE_OIDC_CLIENT_ID` | `aaa-management-ui` | OIDC client |
| Pushgateway URL | `pushgatewayUrl` | — | — | Optional Prometheus Pushgateway for RUM metrics |

Source: `src/config.ts`

---

## Authentication

- Login redirects to the configured OIDC provider (e.g., Keycloak)
- Access token stored in memory via `setAccessToken()` in `src/apiClient.ts`
- Every request includes `Authorization: Bearer {token}`
- HTTP 401 → redirect to OIDC login
- Page refresh clears the token → user is redirected to login

---

## API Client

`src/apiClient.ts` wraps Axios with:

- **JWT injection** — `Authorization` header on every request
- **401 redirect** — clears token, redirects to OIDC login
- **429 auto-retry** — exponential backoff up to 3 retries (500ms → 1s → 2s)
- **RUM metrics** — records per-endpoint request count, total duration, and error count; flushes to Prometheus Pushgateway every 30s and on page unload

Metrics emitted (if Pushgateway is configured):
- `ui_api_call_requests_total{endpoint}`
- `ui_api_call_duration_ms_total{endpoint}`
- `ui_api_call_errors_total{endpoint}`

---

## Project Structure

```
src/
├── main.tsx                 # React entry point
├── App.tsx                  # Route definitions
├── config.ts                # Runtime config (window.APP_CONFIG or Vite env)
├── apiClient.ts             # Axios instance with auth, retry, RUM
├── types.ts                 # TypeScript interfaces (Profile, Pool, RangeConfig, …)
├── components/
│   ├── Layout.tsx           # Shell: sidebar nav, top bar, toast container
│   ├── StatusBadge.tsx      # Colour + text status indicator
│   └── SimProfileDiagram.tsx # Visual IMSI/ICCID/APN relationship diagrams
├── pages/
│   ├── Dashboard.tsx
│   ├── Subscribers.tsx      # SIM profile list/detail/create/bulk import
│   ├── Pools.tsx
│   ├── RoutingDomains.tsx
│   ├── RangeConfigs.tsx     # IMSI range configs + APN pool manager
│   ├── IccidRangeConfigs.tsx # ICCID range configs + IMSI slot manager
│   ├── BulkJobs.tsx
│   ├── SimProfileTypes.tsx
│   └── SimProfileTypesDoc.tsx
└── stores/
    └── toast.ts             # Zustand toast store
```

---

## Kubernetes / Helm

Chart: `charts/aaa-management-ui`

Key defaults (`values.yaml`):

| Setting | Default |
|---------|---------|
| Replicas | 2 |
| Image | `registry.example.com/aaa-management-ui:latest` |
| Service type | ClusterIP, port 80 |
| Ingress host | `ui.aaa-platform.example.com` |
| Strategy | RollingUpdate (maxUnavailable: 0) |
| CPU request/limit | 100m / 500m |
| Memory request/limit | 128Mi / 256Mi |

Two ConfigMaps are mounted:
1. **Nginx config** → `/etc/nginx/conf.d/default.conf`
2. **App config** → `/usr/share/nginx/html/config.js` (sets `window.APP_CONFIG`)

A `nginx-prometheus-exporter` sidecar exposes Nginx metrics on port `9113`. A `ServiceMonitor` is included for Prometheus Operator scraping.

**Grafana alerts defined:**
- `UIPodsDown` — critical when 0 pods are running
- `UIHighConnectionDropRate` — warning on elevated drop rate
- `UIHighPageLoadTime` — warning when p95 page load exceeds 3s

---

## Design Tokens

| Token | Value | Usage |
|-------|-------|-------|
| Primary (amber) | `#F5A623` | Buttons, active nav, progress bars |
| Sidebar (navy) | `#1C2340` | Sidebar background |
| Status active | `#38A169` | Green dot/badge |
| Status suspended | `#F5A623` | Amber dot/badge |
| Status terminated | `#E53E3E` | Red dot/badge |
| Status running | `#3182CE` | Blue pulsing dot (bulk jobs) |
| Page background | `#F4F6F9` | Light grey content area |

Defined in `tailwind.config.cjs` and referenced via Tailwind utility classes throughout the components.
