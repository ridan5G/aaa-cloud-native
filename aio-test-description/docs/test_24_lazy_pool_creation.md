# Test Suite 24 — Lazy Pool Creation (Large Subnets)

## What this test suite validates

Before the lazy-pool refactor, `POST /pools` materialised every host address into `ip_pool_available` at creation time, so a `/12` pool (≈1 M IPs) timed out the request with a 504. After the change, creation only stores the subnet bounds in `ip_pool_subnets`; IPs are claimed in chunks at range-config time and on-demand by `_allocate_ip`. This suite proves:

- Creating a large pool returns within seconds (no eager pre-population).
- Stats correctly report the full subnet capacity even though no rows exist in `ip_pool_available` yet.
- An immediate-mode range over a small slice of the pool only claims the IPs it needs (lazy chunked claim).
- Allocated IPs are real and inside the registered subnet.

The chosen subnet is a `/20` (4093 usable IPs). Big enough that an eager pre-population would be noticeably slow; small enough that we don't need to reserve a `/12`.

## Pre-conditions (Setup)

- Module 24 → IMSI prefix `27877 24 xxxxxxxx`
- Subnet: `100.66.16.0/20` (4093 usable IPs after gateway/last-host reservations)
- Creation budget: **5 seconds** (sanity guard against eager-population regressions)

A single `TestLazyPoolCreation` class runs all four tests sequentially with `@pytest.mark.order(2400)`.

---

## Test 24.1 — Pool creation completes within the time budget

**Goal:** Confirm `POST /pools` for a `/20` is sub-five-seconds.

1. Capture `time.monotonic()`.
2. Send `POST /pools` with `subnet=100.66.16.0/20`.
3. Assert HTTP 201 and elapsed < 5.0 seconds.

## Test 24.2 — Stats reflect the full /20 capacity

**Goal:** Stats are computed from `ip_pool_subnets` bounds, not from materialised `ip_pool_available` rows.

1. `GET /pools/{id}/stats`.
2. Assert `total == 4093`, `allocated == 0`, `available == 4093`.

## Test 24.3 — Immediate-mode range only claims the IPs it needs

**Goal:** Confirm the chunked claim path takes exactly the requested count from the `/20`'s lazy watermark.

1. Create a range config covering 5 IMSIs (`provisioning_mode="immediate"`, `ip_resolution="imsi"`).
2. `GET /pools/{id}/stats`.
3. Assert `allocated == 5`, `available == 4093 - 5 = 4088`.

## Test 24.4 — First-connection returns a real, in-subnet IP

**Goal:** The IP returned by `POST /first-connection` for the first IMSI is inside `100.66.16.0/20`.

1. `POST /first-connection` with the first IMSI of the range and a valid APN.
2. Assert HTTP 200 or 201.
3. Parse the returned `static_ip`. Verify the first two octets are `100.66` and the third octet is between 16 and 31 inclusive (the `/20` range).

---

## Post-conditions (Teardown)

The class deletes the range config (releases the 5 IPs), force-clears any leftover pool IPs in `ip_pool_available`, and deletes the pool. The `/20` had no eager rows to clean up — only the watermark bookkeeping in `ip_pool_subnets`, which CASCADEs with the pool delete.
