# AIO Test Descriptions

All test description documents are in the [docs/](docs/) subfolder.

## Test Index

| File | Description |
|------|-------------|
| [test_01_pools.md](docs/test_01_pools.md) | IP pool CRUD, stats, and enforcement that overlapping CIDRs cannot share a routing domain. |
| [test_01b_radius_warmup.md](docs/test_01b_radius_warmup.md) | Sends one RADIUS packet at suite startup to seed Prometheus counters before the main tests begin. |
| [test_01c_routing_domains.md](docs/test_01c_routing_domains.md) | Routing domain CRUD, CIDR suggestion, duplicate-name rejection, and allowed-prefix enforcement. |
| [test_01d_free_cidr_finder.md](docs/test_01d_free_cidr_finder.md) | End-to-end workflow that suggests a free CIDR block within a domain and creates a pool from it. |
| [test_02_range_configs.md](docs/test_02_range_configs.md) | Full lifecycle of IMSI range configs: create, read, list, update, suspend, delete, and validation. |
| [test_03_iccid_profile.md](docs/test_03_iccid_profile.md) | ICCID-mode profiles where all IMSIs on a card share one IP regardless of APN, including suspend and delete. |
| [test_04_imsi_profile.md](docs/test_04_imsi_profile.md) | IMSI-mode profiles where each IMSI gets its own static IP, with per-IMSI suspend and IP change. |
| [test_05_imsi_apn_profile.md](docs/test_05_imsi_apn_profile.md) | IMSI+APN-mode profiles where each IMSI/APN pair has a dedicated IP, including wildcard APN fallback. |
| [test_06_imsi_ops.md](docs/test_06_imsi_ops.md) | IMSI-level operations on existing profiles: add, remove, lookup, and conflict detection. |
| [test_07_dynamic_alloc.md](docs/test_07_dynamic_alloc.md) | First-connection auto-provisioning: unknown IMSI triggers IP allocation from range config pool, including pool exhaustion and concurrency. |
| [test_07b_dynamic_alloc_modes.md](docs/test_07b_dynamic_alloc_modes.md) | First-connection IP allocation verified across all eight SIM-type and resolution-mode combinations, with idempotency checks. |
| [test_07c_release_ips.md](docs/test_07c_release_ips.md) | IP release via release-ips and IMSI deletion, confirming released IPs are immediately reusable and profiles survive the operation. |
| [test_07e_release_reconnect_all_modes.md](docs/test_07e_release_reconnect_all_modes.md) | Regression guard: after release-ips, the next first-connection must allocate a fresh non-null IP across all four resolution modes. |
| [test_08_iccid_apn_profile.md](docs/test_08_iccid_apn_profile.md) | ICCID-APN mode where a physical card gets one IP per APN, shared by all its IMSIs, with wildcard and suspend tests. |
| [test_09_migration.md](docs/test_09_migration.md) | Validates that data migrated from legacy MariaDB is correctly accessible via the REST API across four subscriber scenarios. |
| [test_10_errors.md](docs/test_10_errors.md) | API error handling: input validation rejections, duplicate conflicts, not-found errors, invalid state transitions, and auth failures. |
| [test_11_performance.md](docs/test_11_performance.md) | Latency benchmarks against 300,000 seeded profiles: p99 thresholds for sequential, concurrent, and bulk-import workloads. |
| [test_12_grafana_metrics.md](docs/test_12_grafana_metrics.md) | Verifies every Prometheus metric powering the Grafana dashboard increments correctly after real operations. |
| [test_12_radius.md](docs/test_12_radius.md) | End-to-end RADIUS UDP authentication: Access-Accept with correct Framed-IP for known subscribers, Access-Reject for suspended or unknown ones. |
| [test_12b_radius_modes.md](docs/test_12b_radius_modes.md) | RADIUS authentication verified across iccid, imsi_apn, and iccid_apn modes, including per-IMSI suspension and first-connection via RADIUS. |
| [test_13_export_and_ip_search.md](docs/test_13_export_and_ip_search.md) | Export API column format, IP-address filter, and all profile list filters (account, status, IMSI prefix, ICCID prefix). |
| [test_14_export_delete_reprovision.md](docs/test_14_export_delete_reprovision.md) | Full export-delete-reimport lifecycle for all four profile types, confirming re-created profiles are active and resolve correctly. |
| [test_15_bulk.md](docs/test_15_bulk.md) | Bulk profile import of 1,500 SIMs via async job, with spot-check lookups, mixed-validity batches, upsert behaviour, and CSV upload. |
| [test_15b_bulk_actions.md](docs/test_15b_bulk_actions.md) | Bulk release-ips and bulk IMSI deletion APIs, tested with both JSON and CSV input and validation error handling. |
| [test_16_lookup_fast_path.md](docs/test_16_lookup_fast_path.md) | Lookup service IMSI format validation and SIM-level suspend/reactivate in both IMSI and IMSI-APN resolution modes. |
| [test_17_immediate_provisioning.md](docs/test_17_immediate_provisioning.md) | Immediate provisioning mode: range config creation triggers a background job that allocates IPs to every SIM before any first-connection. |
| [test_18_nullable_slot_pool.md](docs/test_18_nullable_slot_pool.md) | Regression tests for multi-IMSI ICCID ranges with null slot pool_id relying on per-APN pool overrides for all allocations. |
| [test_19_validation_and_mgmt.md](docs/test_19_validation_and_mgmt.md) | Input validation and CRUD for ICCID range configs: IMSI slot cardinality, APN-pool overrides, skip-ICCID mode, and size alignment. |
| [test_20_imsi_only_immediate.md](docs/test_20_imsi_only_immediate.md) | Skip-ICCID range configs in immediate mode: adding the last slot fires a background job that provisions all virtual cards upfront. |
| [test_21_imsi_only_first_connect.md](docs/test_21_imsi_only_first_connect.md) | Skip-ICCID range configs in first-connect mode: on-demand IP allocation across all four resolution modes, with sibling slot pre-provisioning. |
