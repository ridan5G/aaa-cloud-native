"""
test_01d_free_cidr_finder.py — Free CIDR finder end-to-end workflow

Test cases cover the full operator workflow:
  configure allowed_prefixes on a routing domain → call suggest-cidr → create pool

  1d.1  Happy-path round-trip: domain with allowed_prefixes → suggest-cidr → create pool → 201
  1d.2  GET /pools/{pool_id} after creation → subnet matches suggested_cidr, routing_domain_id matches
  1d.3  Sequential suggestions don't overlap: suggest #1 → pool #1; suggest #2 → pool #2 (no 409)
  1d.4  Patch allowed_prefixes gates suggest-cidr: no prefixes → 422; add prefix → suggest → pool → 201
  1d.5  suggest-cidr size → prefix_len boundary table (sizes 1..511 covering /30..-/22)
  1d.6  Create pool via routing_domain_id (UUID); GET confirms routing_domain_id and name
  1d.7  Large pool at start of prefix is skipped: pool covering first /17 → suggest finds /25 in second /17
  1d.8  Smallest-fitting prefix invariant: in-between sizes pick the smallest p where 2^(32-p)-2 ≥ size
  1d.9  Two consecutive size=14 suggestions return non-overlapping /28s; both pools create successfully
"""
import ipaddress

import httpx
import pytest

from fixtures.pools import create_pool, delete_pool


# ─── Helpers ──────────────────────────────────────────────────────────────────

def create_domain(
    http: httpx.Client,
    name: str,
    allowed_prefixes: list[str] | None = None,
) -> dict:
    """POST /routing-domains and assert 201. Returns response body."""
    body: dict = {"name": name}
    if allowed_prefixes is not None:
        body["allowed_prefixes"] = allowed_prefixes
    resp = http.post("/routing-domains", json=body)
    assert resp.status_code == 201, f"create_domain failed: {resp.status_code} {resp.text}"
    return resp.json()


def delete_domain(http: httpx.Client, domain_id: str) -> None:
    """DELETE /routing-domains/{id} — best-effort teardown (ignores 404/409)."""
    resp = http.delete(f"/routing-domains/{domain_id}")
    if resp.status_code not in (204, 404, 409):
        raise AssertionError(
            f"delete_domain({domain_id}) returned unexpected {resp.status_code}: {resp.text}"
        )


# ─── Test constants ────────────────────────────────────────────────────────────

TD_NAME   = "test-rd-1d-cidr"
TD_PREFIX = "10.88.0.0/16"   # IP space reserved for this module


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestFreeCidrFinderWorkflow:
    """Free CIDR finder end-to-end workflow — tests 1d.1 – 1d.6."""

    # 1d.1 ────────────────────────────────────────────────────────────────────
    def test_01d_1_suggest_and_create_pool(self, http: httpx.Client):
        """Happy-path: domain with allowed_prefixes → suggest-cidr → create pool."""
        domain = create_domain(http, TD_NAME, allowed_prefixes=[TD_PREFIX])
        did = domain["id"]
        pool_id: str | None = None
        try:
            # Find a free CIDR
            resp = http.get(f"/routing-domains/{did}/suggest-cidr", params={"size": 50})
            assert resp.status_code == 200, f"suggest-cidr failed: {resp.status_code} {resp.text}"
            data = resp.json()

            assert "suggested_cidr" in data, "Response must contain suggested_cidr"
            assert "prefix_len"     in data, "Response must contain prefix_len"
            assert "usable_hosts"   in data, "Response must contain usable_hosts"
            assert data["usable_hosts"] >= 50, \
                f"usable_hosts {data['usable_hosts']} < requested 50"
            assert data["routing_domain_id"] == did, \
                f"routing_domain_id mismatch: {data['routing_domain_id']} != {did}"

            suggested_cidr = data["suggested_cidr"]
            # Must fall within the allowed prefix
            suggested_net  = ipaddress.ip_network(suggested_cidr, strict=False)
            allowed_net    = ipaddress.ip_network(TD_PREFIX, strict=False)
            assert suggested_net.subnet_of(allowed_net), \
                f"Suggested CIDR {suggested_cidr} is not within allowed prefix {TD_PREFIX}"

            # Create the pool using the suggested CIDR
            pool = create_pool(
                http,
                subnet=suggested_cidr,
                pool_name="rd-1d-pool-a",
                account_name="TestAccount",
                routing_domain=TD_NAME,
            )
            pool_id = pool["pool_id"]
        finally:
            if pool_id:
                delete_pool(http, pool_id)
            delete_domain(http, did)

    # 1d.2 ────────────────────────────────────────────────────────────────────
    def test_01d_2_pool_subnet_matches_suggestion(self, http: httpx.Client):
        """GET /pools/{pool_id} → subnet equals suggested_cidr, routing_domain_id matches."""
        domain = create_domain(http, TD_NAME, allowed_prefixes=[TD_PREFIX])
        did = domain["id"]
        pool_id: str | None = None
        try:
            resp = http.get(f"/routing-domains/{did}/suggest-cidr", params={"size": 50})
            assert resp.status_code == 200
            suggested_cidr = resp.json()["suggested_cidr"]

            pool = create_pool(
                http,
                subnet=suggested_cidr,
                pool_name="rd-1d-pool-b",
                account_name="TestAccount",
                routing_domain=TD_NAME,
            )
            pool_id = pool["pool_id"]

            # Verify pool reflects the suggested CIDR and domain
            get_resp = http.get(f"/pools/{pool_id}")
            assert get_resp.status_code == 200
            pdata = get_resp.json()

            # Normalise CIDR representation before comparing
            assert ipaddress.ip_network(pdata["subnet"], strict=False) == \
                   ipaddress.ip_network(suggested_cidr, strict=False), \
                f"Pool subnet {pdata['subnet']} != suggested {suggested_cidr}"
            assert pdata["routing_domain_id"] == did, \
                f"routing_domain_id mismatch: {pdata['routing_domain_id']} != {did}"
            assert pdata["routing_domain"] == TD_NAME
        finally:
            if pool_id:
                delete_pool(http, pool_id)
            delete_domain(http, did)

    # 1d.3 ────────────────────────────────────────────────────────────────────
    def test_01d_3_sequential_suggestions_dont_overlap(self, http: httpx.Client):
        """suggest #1 → pool #1; suggest #2 → different CIDR; pool #2 → 201 (no overlap)."""
        domain = create_domain(http, TD_NAME, allowed_prefixes=[TD_PREFIX])
        did = domain["id"]
        pool_id_1: str | None = None
        pool_id_2: str | None = None
        try:
            # First suggestion + pool
            resp1 = http.get(f"/routing-domains/{did}/suggest-cidr", params={"size": 50})
            assert resp1.status_code == 200
            cidr_1 = resp1.json()["suggested_cidr"]

            pool1 = create_pool(
                http,
                subnet=cidr_1,
                pool_name="rd-1d-seq-pool-1",
                account_name="TestAccount",
                routing_domain=TD_NAME,
            )
            pool_id_1 = pool1["pool_id"]

            # Second suggestion must be different and non-overlapping
            resp2 = http.get(f"/routing-domains/{did}/suggest-cidr", params={"size": 50})
            assert resp2.status_code == 200
            cidr_2 = resp2.json()["suggested_cidr"]

            assert cidr_2 != cidr_1, \
                f"suggest-cidr returned the same CIDR {cidr_1} after first pool was created"

            net_1 = ipaddress.ip_network(cidr_1, strict=False)
            net_2 = ipaddress.ip_network(cidr_2, strict=False)
            assert not net_1.overlaps(net_2), \
                f"Suggested CIDRs overlap: {cidr_1} and {cidr_2}"

            # Creating the second pool must succeed (no 409 overlap)
            pool2 = create_pool(
                http,
                subnet=cidr_2,
                pool_name="rd-1d-seq-pool-2",
                account_name="TestAccount",
                routing_domain=TD_NAME,
            )
            pool_id_2 = pool2["pool_id"]
        finally:
            if pool_id_2:
                delete_pool(http, pool_id_2)
            if pool_id_1:
                delete_pool(http, pool_id_1)
            delete_domain(http, did)

    # 1d.4 ────────────────────────────────────────────────────────────────────
    def test_01d_4_patch_prefixes_then_suggest(self, http: httpx.Client):
        """Domain with no prefixes → 422; PATCH to add prefix → suggest → create pool → 201."""
        domain = create_domain(http, TD_NAME)  # no allowed_prefixes
        did = domain["id"]
        pool_id: str | None = None
        try:
            # Without allowed_prefixes suggest-cidr must fail
            resp = http.get(f"/routing-domains/{did}/suggest-cidr", params={"size": 10})
            assert resp.status_code == 422, \
                f"Expected 422 no_allowed_prefixes, got {resp.status_code}: {resp.text}"
            assert resp.json().get("error") == "no_allowed_prefixes"

            # Patch in the allowed prefix
            patch_resp = http.patch(
                f"/routing-domains/{did}",
                json={"allowed_prefixes": [TD_PREFIX]},
            )
            assert patch_resp.status_code == 200, \
                f"PATCH allowed_prefixes failed: {patch_resp.status_code} {patch_resp.text}"

            # Now suggest-cidr should succeed
            resp2 = http.get(f"/routing-domains/{did}/suggest-cidr", params={"size": 10})
            assert resp2.status_code == 200, \
                f"suggest-cidr after PATCH failed: {resp2.status_code} {resp2.text}"
            suggested_cidr = resp2.json()["suggested_cidr"]

            # And the suggested CIDR must be usable for pool creation
            pool = create_pool(
                http,
                subnet=suggested_cidr,
                pool_name="rd-1d-patch-pool",
                account_name="TestAccount",
                routing_domain=TD_NAME,
            )
            pool_id = pool["pool_id"]
        finally:
            if pool_id:
                delete_pool(http, pool_id)
            delete_domain(http, did)

    # 1d.5 ────────────────────────────────────────────────────────────────────
    def test_01d_5_suggest_size_to_prefix_len(self, http: httpx.Client):
        """suggest-cidr size → prefix_len across the full boundary table.

        Each row probes either an exact power-of-2 boundary (e.g. size=6→/29 with
        usable=6) or one host past it (size=7→/28 with usable=14). Validates that
        the chosen prefix:
          * matches the expected prefix_len,
          * has usable_hosts == 2^(32-p)-2,
          * provides at least `size` usable hosts,
          * lives inside TD_PREFIX.
        """
        cases = [
            # (size, expected_prefix_len)  usable = 2^(32-p) - 2
            (1,    30),  # usable=2
            (2,    30),
            (3,    29),  # usable=6
            (6,    29),
            (7,    28),  # usable=14
            (14,   28),
            (15,   27),  # usable=30
            (31,   26),  # usable=62
            (63,   25),  # usable=126
            (127,  24),  # usable=254
            (254,  24),
            (255,  23),  # usable=510
            (510,  23),
            (511,  22),  # usable=1022
        ]
        td_prefix_net = ipaddress.ip_network(TD_PREFIX, strict=False)
        for size, expected_prefix_len in cases:
            domain = create_domain(
                http,
                f"{TD_NAME}-sz{size}",
                allowed_prefixes=[TD_PREFIX],
            )
            did = domain["id"]
            try:
                resp = http.get(
                    f"/routing-domains/{did}/suggest-cidr", params={"size": size}
                )
                assert resp.status_code == 200, \
                    f"size={size}: Expected 200, got {resp.status_code}: {resp.text}"
                data = resp.json()

                assert data["prefix_len"] == expected_prefix_len, \
                    f"size={size}: expected prefix_len={expected_prefix_len}, got {data['prefix_len']}"

                expected_usable = 2 ** (32 - expected_prefix_len) - 2
                assert data["usable_hosts"] == expected_usable, \
                    f"size={size}: expected usable_hosts={expected_usable}, got {data['usable_hosts']}"
                assert data["usable_hosts"] >= size, \
                    f"size={size}: usable_hosts {data['usable_hosts']} < requested size"

                suggested_net = ipaddress.ip_network(data["suggested_cidr"], strict=False)
                assert suggested_net.subnet_of(td_prefix_net), \
                    f"size={size}: suggested {data['suggested_cidr']} not within {TD_PREFIX}"
            finally:
                delete_domain(http, did)

    # 1d.6 ────────────────────────────────────────────────────────────────────
    def test_01d_6_create_pool_by_routing_domain_id(self, http: httpx.Client):
        """Create pool using routing_domain_id (UUID); GET confirms id and name."""
        domain = create_domain(http, TD_NAME, allowed_prefixes=[TD_PREFIX])
        did = domain["id"]
        pool_id: str | None = None
        try:
            resp = http.get(f"/routing-domains/{did}/suggest-cidr", params={"size": 50})
            assert resp.status_code == 200
            suggested_cidr = resp.json()["suggested_cidr"]

            # Use routing_domain_id (UUID), not the name string
            create_resp = http.post("/pools", json={
                "name":              "rd-1d-uuid-pool",
                "account_name":      "TestAccount",
                "routing_domain_id": did,
                "subnet":            suggested_cidr,
            })
            assert create_resp.status_code == 201, \
                f"Expected 201, got {create_resp.status_code}: {create_resp.text}"
            pool_id = create_resp.json()["pool_id"]

            # GET the pool and verify both routing_domain_id and name are present
            get_resp = http.get(f"/pools/{pool_id}")
            assert get_resp.status_code == 200
            pdata = get_resp.json()
            assert pdata["routing_domain_id"] == did, \
                f"routing_domain_id mismatch: {pdata['routing_domain_id']} != {did}"
            assert pdata["routing_domain"] == TD_NAME, \
                f"routing_domain name mismatch: {pdata['routing_domain']} != {TD_NAME}"
        finally:
            if pool_id:
                delete_pool(http, pool_id)
            delete_domain(http, did)

    # 1d.7 ────────────────────────────────────────────────────────────────────
    def test_01d_7_large_pool_at_start_skipped(self, http: httpx.Client):
        """
        Regression: a large pool covering the first half of the allowed prefix
        must not prevent suggest-cidr from finding a free block in the second half.

        10.88.0.0/16 split into two /17s:
          - 10.88.0.0/17  — occupied (one pool covering 32,768 addresses = 256 /25 blocks)
          - 10.88.128.0/17 — free

        With the old 10,000-candidate cap the algorithm would exhaust all tries inside
        the first /17 and falsely return 404. The interval-based scan jumps past it.
        """
        # TD_PREFIX = "10.88.0.0/16"
        first_half  = "10.88.0.0/17"    # blocks all 256 /25s in the first half
        second_half = ipaddress.ip_network("10.88.128.0/17", strict=False)

        domain = create_domain(http, TD_NAME, allowed_prefixes=[TD_PREFIX])
        did = domain["id"]
        blocking_pool_id: str | None = None
        try:
            # Create a single pool that covers the entire first /17
            blocking_pool = create_pool(
                http,
                subnet=first_half,
                pool_name="rd-1d-blocker",
                account_name="TestAccount",
                routing_domain=TD_NAME,
            )
            blocking_pool_id = blocking_pool["pool_id"]

            # suggest-cidr must find a free /25 — somewhere in the second /17
            resp = http.get(f"/routing-domains/{did}/suggest-cidr", params={"size": 50})
            assert resp.status_code == 200, \
                f"Expected 200 (interval scan should skip the /17 blocker), " \
                f"got {resp.status_code}: {resp.text}"

            data = resp.json()
            suggested_cidr = data["suggested_cidr"]
            suggested_net   = ipaddress.ip_network(suggested_cidr, strict=False)

            # Must NOT overlap the blocking pool
            assert not suggested_net.overlaps(ipaddress.ip_network(first_half, strict=False)), \
                f"Suggestion {suggested_cidr} overlaps the blocking pool {first_half}"

            # Must still be within the allowed prefix
            assert suggested_net.subnet_of(ipaddress.ip_network(TD_PREFIX, strict=False)), \
                f"Suggestion {suggested_cidr} is outside allowed prefix {TD_PREFIX}"

            # Must fall in the free second half
            assert suggested_net.subnet_of(second_half), \
                f"Suggestion {suggested_cidr} is not in the free second half {second_half}"
        finally:
            if blocking_pool_id:
                delete_pool(http, blocking_pool_id)
            delete_domain(http, did)

    # 1d.8 ────────────────────────────────────────────────────────────────────
    def test_01d_8_smallest_fitting_prefix_invariant(self, http: httpx.Client):
        """In-between sizes pick the SMALLEST prefix that fits, not a larger one.

        For each (size, expected_p) the suggester must return prefix_len=expected_p
        AND the next-smaller prefix (expected_p + 1) must NOT have enough usable
        hosts for `size`. Confirms the chosen subnet is minimal-sufficient.
        """
        cases = [
            # (size, expected_smallest_prefix_len)
            (10,   28),   # 14 fits, 6 does not
            (20,   27),   # 30 fits, 14 does not
            (100,  25),   # 126 fits, 62 does not
            (200,  24),   # 254 fits, 126 does not
        ]
        for size, expected_p in cases:
            # Sanity-check the case definition itself: the next-smaller prefix
            # genuinely cannot accommodate `size`.
            next_smaller_usable = 2 ** (32 - (expected_p + 1)) - 2
            assert next_smaller_usable < size, \
                f"case bug: size={size} fits in /{expected_p + 1} (usable={next_smaller_usable})"

            domain = create_domain(
                http,
                f"{TD_NAME}-fit{size}",
                allowed_prefixes=[TD_PREFIX],
            )
            did = domain["id"]
            try:
                resp = http.get(
                    f"/routing-domains/{did}/suggest-cidr", params={"size": size}
                )
                assert resp.status_code == 200, \
                    f"size={size}: Expected 200, got {resp.status_code}: {resp.text}"
                data = resp.json()
                assert data["prefix_len"] == expected_p, \
                    f"size={size}: expected smallest prefix /{expected_p}, " \
                    f"got /{data['prefix_len']} (usable={data['usable_hosts']})"
                assert data["usable_hosts"] >= size
            finally:
                delete_domain(http, did)

    # 1d.9 ────────────────────────────────────────────────────────────────────
    def test_01d_9_two_28s_no_overlap_size14(self, http: httpx.Client):
        """Two consecutive size=14 suggestions yield non-overlapping /28s; both pools create."""
        domain = create_domain(http, f"{TD_NAME}-two28", allowed_prefixes=[TD_PREFIX])
        did = domain["id"]
        pool_id_a: str | None = None
        pool_id_b: str | None = None
        try:
            resp_a = http.get(
                f"/routing-domains/{did}/suggest-cidr", params={"size": 14}
            )
            assert resp_a.status_code == 200, f"first suggest failed: {resp_a.text}"
            data_a = resp_a.json()
            assert data_a["prefix_len"] == 28
            cidr_a = data_a["suggested_cidr"]

            pool_a = create_pool(
                http,
                subnet=cidr_a,
                pool_name="rd-1d-two28-a",
                account_name="TestAccount",
                routing_domain=f"{TD_NAME}-two28",
            )
            pool_id_a = pool_a["pool_id"]

            resp_b = http.get(
                f"/routing-domains/{did}/suggest-cidr", params={"size": 14}
            )
            assert resp_b.status_code == 200, f"second suggest failed: {resp_b.text}"
            data_b = resp_b.json()
            assert data_b["prefix_len"] == 28
            cidr_b = data_b["suggested_cidr"]

            net_a = ipaddress.ip_network(cidr_a, strict=False)
            net_b = ipaddress.ip_network(cidr_b, strict=False)
            td_prefix_net = ipaddress.ip_network(TD_PREFIX, strict=False)

            assert cidr_b != cidr_a, \
                f"second suggestion returned the same /28 {cidr_a} after pool was created"
            assert not net_a.overlaps(net_b), \
                f"suggested /28s overlap: {cidr_a} and {cidr_b}"
            assert net_a.subnet_of(td_prefix_net) and net_b.subnet_of(td_prefix_net), \
                f"suggestions outside {TD_PREFIX}: {cidr_a}, {cidr_b}"

            pool_b = create_pool(
                http,
                subnet=cidr_b,
                pool_name="rd-1d-two28-b",
                account_name="TestAccount",
                routing_domain=f"{TD_NAME}-two28",
            )
            pool_id_b = pool_b["pool_id"]
        finally:
            if pool_id_b:
                delete_pool(http, pool_id_b)
            if pool_id_a:
                delete_pool(http, pool_id_a)
            delete_domain(http, did)
