# Test Suite 23 — Multi-Subnet IP Pool Expansion

## What this test suite validates

A single `ip_pools` row can now span multiple CIDR blocks. Each block is recorded in `ip_pool_subnets` with its own `next_ip_offset` watermark and a `priority` ordering — allocations drain priority 0 (the primary subnet) first and spill into priority 1 once the primary is exhausted. This suite verifies that pool creation stays fast (lazy O(1)), stats correctly aggregate across subnets, overlap detection catches CIDRs that conflict with either the primary `ip_pools.subnet` or any registered `ip_pool_subnets.subnet`, and allocation spans both subnets when the range size exceeds the primary capacity.

## Pre-conditions (Setup)

- Module 23 → IMSI prefix `27877 23 xxxxxxxx`
- Primary subnet: `100.66.0.0/29` (5 usable IPs after default gateway/last-host reservations)
- Secondary subnet: `100.66.0.16/29` (5 usable IPs)
- Overlap subnet for the negative test: `100.66.0.4/30` (overlaps the primary)

A single `TestPoolMultiSubnet` class runs all five tests sequentially with `@pytest.mark.order(2300)`.

---

## Test 23.1 — Pool creation with primary subnet is lazy / fast

**Goal:** Confirm `POST /pools` with the primary subnet completes in well under five seconds even for the new schema (lazy creation must not regress).

1. Send `POST /pools` with `subnet=100.66.0.0/29`.
2. Assert HTTP 201 and capture the elapsed wall-clock.
3. Assert elapsed < 5.0 seconds (sanity guard against accidental upfront `INSERT INTO ip_pool_available` work).

## Test 23.2 — Stats reflect primary subnet capacity

**Goal:** `GET /pools/{id}/stats` aggregates `ip_pool_subnets` rows.

1. `GET /pools/{id}/stats`.
2. Assert `total == 5`, `allocated == 0`, `available == 5`.

## Test 23.3 — Adding a secondary subnet sums into stats

**Goal:** `POST /pools/{id}/subnets` registers the new CIDR and the stats endpoint sums both subnets.

1. `POST /pools/{id}/subnets` with `subnet=100.66.0.16/29`.
2. Assert HTTP 201.
3. `GET /pools/{id}/stats`.
4. Assert `total == 10`, `allocated == 0`, `available == 10`.

## Test 23.4 — Overlap detection rejects an overlapping CIDR

**Goal:** Confirm the UNION-based overlap query catches a CIDR that overlaps either the primary `ip_pools.subnet` or any `ip_pool_subnets.subnet`.

1. `POST /pools/{id}/subnets` with `subnet=100.66.0.4/30` (overlaps the primary `100.66.0.0/29`).
2. Assert HTTP 409.
3. Assert response body `error` is `"pool_overlap"` or `"subnet_overlap"`.

## Test 23.5 — Allocation drains priority 0 then spills to priority 1

**Goal:** A range bigger than the primary capacity must allocate from both subnets, in priority order.

1. Create a range config covering 8 IMSIs (range size > primary capacity of 5) with `ip_resolution="imsi"` and `provisioning_mode="immediate"`. The immediate-mode background job claims all 8 IPs synchronously.
2. `GET /pools/{id}/stats`.
3. Assert `allocated == 8` and `available == 10 - 8 = 2`.
4. `POST /first-connection` for the first IMSI in the range and verify the returned IP starts with `100.66.0.` — proving the allocation came from one of the two registered subnets.

---

## Post-conditions (Teardown)

The class deletes the range config (releases all 8 IPs), force-clears any leftover pool IPs in `ip_pool_available`, and deletes the pool. Both `ip_pool_subnets` rows are cleaned up via the pool's CASCADE.
