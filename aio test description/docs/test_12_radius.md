# Test Suite 12 — RADIUS Server End-to-End Authentication

## What this test suite validates

This suite sends real UDP RADIUS Access-Request packets to the `aaa-radius-server` component and verifies the complete single-call AAA (Authentication, Authorization, Accounting) flow. When a device requests access, the RADIUS server consults the lookup service, which either resolves a pre-provisioned subscriber profile or triggers a first-connection to auto-provision one. The suite checks that Access-Accept is returned with the correct Framed-IP-Address for known subscribers, Access-Reject is returned for suspended or unknown subscribers, and that various 3GPP RADIUS VSA (Vendor-Specific Attribute) fields are parsed and forwarded correctly. It also validates RADIUS protocol compliance (response authenticator verification).

**Prerequisites:** The `aaa-radius-server` must be reachable at `RADIUS_HOST`:`RADIUS_PORT` (defaults: `localhost:1812`). If it is not reachable, the entire test class is automatically skipped.

**Note:** This suite is tagged `@pytest.mark.radius`. All tests are skipped if the RADIUS server is not available.

## Pre-conditions (Setup)

1. Any stale profiles or pools from a previous interrupted run are cleaned up.
2. **Pool A** (`100.65.120.200/29`, 6 usable IPs) is created with pool name `pool-radius-known-12`.
3. A pre-provisioned subscriber profile is created for a known IMSI (`278771200000001`) with static IP `100.65.120.201`. This simulates an operator-provisioned subscriber.
4. **Pool B** (`100.65.120.208/29`, 6 usable IPs) is created with pool name `pool-radius-fc-12`.
5. A range configuration is registered for IMSI range `278771200001001`–`278771200001099`, pointing to Pool B. This enables the first-connection auto-provisioning path for new subscribers in this range.

---

## Test 12.1 — Pre-conditions: profile exists and lookup resolves before RADIUS tests

**Goal:** Confirm that the pre-provisioned profile is visible in the lookup service before any RADIUS packets are sent, and that the lookup accepts the optional `use_case_id` parameter.

1. Send a lookup request for the known IMSI without `use_case_id`.
2. Confirm HTTP 200 and `static_ip` = `100.65.120.201`.
3. Send a lookup request for the same IMSI with `use_case_id` = `"0800"` (as a RADIUS server with 3GPP-Charging-Characteristics would send).
4. Confirm HTTP 200 and the same static IP.

---

## Test 12.2 — Known subscriber gets Access-Accept

**Goal:** A RADIUS request for a pre-provisioned subscriber returns Access-Accept.

1. Send a RADIUS Access-Request packet for the known IMSI with the test APN.
2. Confirm the response code is 2 (Access-Accept).

---

## Test 12.2b — Access-Accept is consistent across 100 successive requests

**Goal:** Under repeated authentication attempts for the same IMSI, the server must reliably return Access-Accept every time.

1. Send 100 successive RADIUS Access-Requests for the known IMSI.
2. Collect results; confirm all 100 responses are Access-Accept.
3. Report any failures together at the end (so all 100 always run, even if some fail).

---

## Test 12.3 — Framed-IP-Address in Accept matches the provisioned static IP

**Goal:** The IP address included in the Access-Accept packet must exactly match what was stored in the subscriber's profile.

1. Send a RADIUS Access-Request for the known IMSI.
2. Confirm the response is Access-Accept.
3. Confirm the `Framed-IP-Address` attribute in the response equals `100.65.120.201`.

---

## Test 12.4 — Suspended subscriber gets Access-Reject

**Goal:** After suspending a subscriber's profile, the RADIUS server must deny network access for that subscriber.

1. Update the known subscriber's profile status to `suspended`.
2. Confirm the update succeeds.
3. Send a RADIUS Access-Request for the known IMSI.
4. Confirm the response is Access-Reject (code 3).
5. Verify via the API that the profile is indeed in `suspended` status.

---

## Test 12.5 — Reactivated subscriber gets Access-Accept with the original IP

**Goal:** After reactivating a suspended subscriber, the RADIUS server immediately restores access with the same IP as before.

1. Update the known subscriber's profile status back to `active`.
2. Confirm the update succeeds.
3. Send a RADIUS Access-Request for the known IMSI.
4. Confirm Access-Accept.
5. Confirm `Framed-IP-Address` = `100.65.120.201` (the original IP is unchanged).

---

## Test 12.6 — First-connection via RADIUS auto-provisions a new subscriber

**Goal:** When a RADIUS request arrives for an IMSI that has no existing profile, the lookup service triggers first-connection internally, allocates an IP from Pool B, and the RADIUS server returns Access-Accept with the new IP.

1. Confirm the IMSI (`278771200001001`) has no pre-existing profile.
2. Send a RADIUS Access-Request for this IMSI, including IMEI and `charging_chars = "0800"`.
3. Confirm Access-Accept with a non-null Framed-IP-Address from Pool B's subnet.
4. Record the allocated IP for the idempotency test (test 12.7).
5. Retrieve the auto-created subscriber profile via the API and record its `sim_id` for teardown.
6. Send a lookup request for this IMSI and confirm it now resolves to the same IP included in the Accept.

---

## Test 12.7 — Second request for the same auto-provisioned IMSI returns the same IP (idempotency)

**Goal:** Once a subscriber is auto-provisioned, all subsequent RADIUS requests must return the same Framed-IP-Address — no new IP is allocated.

1. Send a second RADIUS Access-Request for the same IMSI (`278771200001001`).
2. Confirm Access-Accept.
3. Confirm the Framed-IP-Address is identical to the IP allocated in test 12.6.

---

## Test 12.8 — IMSI outside all range configurations gets Access-Reject

**Goal:** An IMSI that is not covered by any range configuration cannot have a profile auto-provisioned; the RADIUS server must reject the request.

1. Send a RADIUS Access-Request for an out-of-range IMSI (`278771209999001`).
2. Confirm Access-Reject (code 3).

---

## Test 12.9 — Response Authenticator is cryptographically valid

**Goal:** The RADIUS server must produce a correctly signed response (RFC 2865 §3 compliance). The test constructs a raw RADIUS packet, sends it, receives the response, and verifies the response authenticator using the shared secret.

1. Construct a raw RADIUS Access-Request packet with a specific packet ID.
2. Send the packet directly over UDP to the RADIUS server.
3. Receive the raw response.
4. Verify the response authenticator using MD5(Code|ID|Length|RequestAuth|Attrs|Secret).
5. Confirm verification passes.

---

## Test 12.10 — Access-Reject does not include a Framed-IP-Address

**Goal:** RFC 2865 prohibits including Framed-IP-Address in an Access-Reject. Sending an IP in a Reject could cause the network access server to route traffic incorrectly.

1. Send a RADIUS Access-Request for the out-of-range IMSI.
2. Confirm Access-Reject.
3. Confirm the response does not contain a Framed-IP-Address attribute (attribute type 8).

---

## Test 12.11 — Full 3GPP AVP request is accepted with the correct Framed-IP

**Goal:** A RADIUS packet carrying the full set of standard and 3GPP Vendor-Specific Attributes (as a real PGW/GGSN/SMF would send) must be parsed correctly and still return Access-Accept with the right IP.

1. Send a RADIUS Access-Request containing all standard RADIUS attributes plus 3GPP VSAs: NAS-IP-Address, NAS-Identifier, Service-Type, Framed-Protocol, NAS-Port-Type, Calling-Station-Id (APN), 3GPP-IMSI-MCC-MNC, 3GPP-GGSN-MCC-MNC, 3GPP-NSAPI, 3GPP-Selection-Mode, 3GPP-Charging-Characteristics, 3GPP-IMEISV, 3GPP-RAT-Type, 3GPP-User-Location-Info, 3GPP-MS-TimeZone.
2. Confirm Access-Accept.
3. Confirm `Framed-IP-Address` = `100.65.120.201`.
4. Confirm the Framed-IP-Address attribute (type 8) is present in the raw response.

---

## Test 12.12 — 3GPP-IMSI VSA takes precedence over User-Name when both are present

**Goal:** The RADIUS server must use the 3GPP-IMSI VSA (vendor 10415, attribute type 1) as the authoritative IMSI, not the User-Name field, when both are present in the same packet.

1. Construct a raw RADIUS Access-Request where:
   - The User-Name field contains an out-of-range IMSI (which would result in Access-Reject if used).
   - The 3GPP-IMSI VSA contains the known subscriber IMSI (which resolves to Accept).
2. Send the packet and receive the response.
3. Confirm Access-Accept — this proves the server used the VSA, not the User-Name.
4. Confirm `Framed-IP-Address` = `100.65.120.201` (the known subscriber's IP).

---

## Test 12.13 — 3GPP-Charging-Characteristics is forwarded as `use_case_id` to the lookup service

**Goal:** The RADIUS server must extract the Charging-Characteristics VSA from the RADIUS packet and pass it as `use_case_id` in its call to the lookup service. This is validated indirectly by confirming the end-to-end path still produces Access-Accept.

1. Confirm the lookup service correctly handles a request with `use_case_id = "0800"` by sending a direct lookup and checking the IP.
2. Send a full RADIUS Access-Request with `charging_chars = "0800"`.
3. Confirm Access-Accept.
4. Confirm `Framed-IP-Address` = `100.65.120.201`.

---

## Test 12.14 — Charging-Characteristics value is forwarded correctly in first-connection

**Goal:** When first-connection is triggered by a RADIUS request, the `use_case_id` in the first-connection POST body must match the `charging_chars` value from the RADIUS packet (not a hard-coded default).

1. Confirm that IMSI #2 for first-connection (`278771200001002`) has no existing profile.
2. Send a RADIUS Access-Request for this IMSI with `charging_chars = "0900"` (a different value than the default `"0800"` used elsewhere).
3. Confirm Access-Accept with a non-null Framed-IP-Address.
4. Record the allocated IP and the auto-created `sim_id` for teardown.

---

## Post-conditions (Teardown)

1. All subscriber profiles created during tests (the pre-provisioned profile and any auto-provisioned profiles) are deleted.
2. The first-connection range configuration is deleted.
3. Pool A (`pool-radius-known-12`) is deleted.
4. Pool B (`pool-radius-fc-12`) is deleted.
