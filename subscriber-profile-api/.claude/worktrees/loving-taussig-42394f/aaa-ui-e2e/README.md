# aaa-ui-e2e

Playwright end-to-end regression tests for the `aaa-management-ui` React dashboard.

This suite runs **independently** from the backend regression tester (`aaa-regression-tester`) and is **not** triggered by `make test` or `make deploy`. Run it explicitly via `make test-ui`.

---

## Quick start

```bash
# 1. Install Playwright + browsers (first time only)
cd aaa-ui-e2e
npm install
npx playwright install chromium

# 2. Expose the deployed UI (run in a separate terminal, keep it running)
make port-forward-ui        # UI available at http://localhost:8090

# 3. Run the suite
make test-ui                # headless
make test-ui-headed         # with browser window visible
make test-ui-report         # open last HTML report
```

### Against the Vite dev server (no k8s)

```bash
# In aaa-management-ui/
npm run dev                 # serves at http://localhost:5173

# In a separate terminal, from repo root:
UI_BASE_URL=http://localhost:5173 make test-ui
```

---

## Configuration

| Env var        | Default                   | Purpose                                   |
|----------------|---------------------------|-------------------------------------------|
| `UI_BASE_URL`  | `http://localhost:8090`   | Base URL the browser targets              |

`playwright.config.ts` sets `bail: 1` — the first failing test aborts the run. Combined with the `00_` filename prefix on the access spec, this means a broken/unreachable UI skips the rest of the suite instead of producing a wall of unrelated failures.

---

## Directory layout

```
aaa-ui-e2e/
├── package.json
├── playwright.config.ts
├── tsconfig.json
└── tests/
    ├── 00_access.spec.ts           # connectivity gate — runs first
    ├── navigation.spec.ts          # sidebar + route transitions
    ├── dashboard.spec.ts           # stat cards, pool util, quick actions
    ├── pools.spec.ts               # list, headers, New Pool modal
    ├── routing-domains.spec.ts     # FULL CRUD with cleanup
    ├── range-configs.spec.ts       # IMSI range configs list
    ├── iccid-range-configs.spec.ts # SIM range configs list + nav
    ├── subscribers.spec.ts         # SIMs page: heading, filters, actions
    ├── bulk-jobs.spec.ts           # bulk jobs list + status badge
    └── sim-profile-types.spec.ts   # profile types page + nav
```

---

## Conventions

### Access check gates the suite
`00_access.spec.ts` verifies the UI is reachable and serves HTML. Because `bail: 1` is set in the Playwright config, any failure here aborts the remaining specs — so the suite fails fast with a clear signal when the UI is down, port-forward is missing, or `UI_BASE_URL` points somewhere wrong.

### CRUD tests and live data
Only `routing-domains.spec.ts` creates and mutates data. It uses an `e2e-test-${Date.now()}` prefix so anything leftover is trivially identifiable, and cleans up via the UI's delete flow in the same test.

Other list pages (`pools`, `range-configs`, `iccid-range-configs`) verify list rendering and modal open/close **only** — creating those entities requires coordinated IP/IMSI/ICCID ranges that would collide with real data in a shared environment.

### Selectors
Prefer user-facing queries (`getByRole`, `getByText`, `getByLabel`, `getByPlaceholder`) over CSS selectors. This keeps tests resilient to styling changes and documents what the user actually sees.

### Skipping gracefully
Specs that need table data use `test.skip()` when the page is in its empty state, instead of failing. This lets the suite pass on a freshly-deployed empty cluster.

---

## Adding a new spec

1. Drop a new `*.spec.ts` file under `tests/`.
2. If it mutates server state, use the `e2e-test-` prefix and clean up at the end of the test.
3. Use `page.goto('/route')` — the `baseURL` is injected from `UI_BASE_URL`.
4. Prefer role/text queries. Grep existing specs for patterns.

---

## Why this is separate from `aaa-regression-tester`

- **Different runtime**: Playwright (Node.js/TypeScript) vs pytest (Python).
- **Different target**: a browser-rendered UI vs REST APIs directly.
- **Different environment needs**: needs a running UI (nginx + static build, or Vite dev) + port-forward, while the backend suite runs as a K8s Job against services in-cluster.
- **Different cadence**: backend regression is part of `make test` and runs on every deploy; UI E2E is an opt-in smoke check you run when touching the UI.

Keeping them apart means the backend flow stays fast and k8s-native, and the UI suite stays lightweight (no K8s Job, no Helm chart, no image build).

---

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| `00_access` fails with connection refused | `make port-forward-ui` isn't running |
| `00_access` passes, nav tests fail | UI loads but routing/React broken — check browser console via `--headed` |
| All CRUD tests skipped | List pages are empty; deploy seed data or run against a populated cluster |
| Tests hang on navigation | `UI_BASE_URL` points to a host that accepts TCP but returns slowly (wrong ingress?) |
| "browserType.launch: Executable doesn't exist" | Run `npx playwright install chromium` |

View traces and screenshots from failed runs with `make test-ui-report`.
