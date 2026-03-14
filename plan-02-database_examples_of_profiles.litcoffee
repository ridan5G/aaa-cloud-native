$ kubectl exec -it aaa-postgres-1 -n aaa-platform -- psql -U postgres aaa
Defaulted container "postgres" out of: postgres, bootstrap-controller (init)
psql (15.6 (Debian 15.6-1.pgdg110+2))
Type "help" for help.

aaa-# \dt
                List of relations
 Schema |         Name         | Type  |  Owner
--------+----------------------+-------+----------
 public | iccid_range_configs  | table | postgres
 public | imsi_range_configs   | table | postgres
 public | ip_pool_available    | table | postgres
 public | ip_pools             | table | postgres
 public | subscriber_apn_ips   | table | postgres
 public | subscriber_iccid_ips | table | postgres
 public | subscriber_imsis     | table | postgres
 public | subscriber_profiles  | table | postgres
(8 rows)

aaa-# SELECT * FROM iccid_range_configs;
SELECT * FROM imsi_range_configs;
SELECT * FROM ip_pool_available;
SELECT * FROM ip_pools;
SELECT * FROM subscriber_apn_ips;
SELECT * FROM subscriber_iccid_ips;
SELECT * FROM subscriber_imsis;
SELECT * FROM subscriber_profiles;


aaa=# SELECT * FROM subscriber_apn_ips;
 id |      imsi       |   apn    |  static_ip   | pool_id | pool_name |          created_at           |          updated_at
----+-----------------+----------+--------------+---------+-----------+-------------------------------+-------------------------------
  1 | 278770200000001 |          | 100.65.2.1   |         |           | 2026-03-12 16:10:29.880642+00 | 2026-03-12 16:10:29.880642+00
  2 | 278770300000001 | internet | 100.65.3.1   |         |           | 2026-03-12 16:10:29.880642+00 | 2026-03-12 16:10:29.880642+00
  3 | 278770300000001 |          | 100.65.3.254 |         |           | 2026-03-12 16:10:29.880642+00 | 2026-03-12 16:10:29.880642+00
(3 rows)

aaa=# SELECT * FROM subscriber_iccid_ips;
 id |              device_id               | apn | static_ip  | pool_id | pool_name |          created_at           |          updated_at
----+--------------------------------------+-----+------------+---------+-----------+-------------------------------+-------------------------------
  1 | aaaaaaaa-0001-0000-0000-000000000001 |     | 100.65.1.1 |         |           | 2026-03-12 16:10:29.880642+00 | 2026-03-12 16:10:29.880642+00
(1 row)

aaa=# \SELECT * FROM subscriber_imsis;
invalid command \SELECT
Try \? for help.
aaa=# SELECT * FROM subscriber_iccid_ips;
 id |              device_id               | apn | static_ip  | pool_id | pool_name |          created_at           |          updated_at
----+--------------------------------------+-----+------------+---------+-----------+-------------------------------+-------------------------------
  1 | aaaaaaaa-0001-0000-0000-000000000001 |     | 100.65.1.1 |         |           | 2026-03-12 16:10:29.880642+00 | 2026-03-12 16:10:29.880642+00
(1 row)

aaa=# SELECT * FROM subscriber_imsis;
      imsi       |              device_id               | status | priority |          created_at           |          updated_at
-----------------+--------------------------------------+--------+----------+-------------------------------+-------------------------------
 278770200000001 | aaaaaaaa-0002-0000-0000-000000000001 | active |        1 | 2026-03-12 16:10:29.880642+00 | 2026-03-12 16:10:29.880642+00
 278770100000001 | aaaaaaaa-0001-0000-0000-000000000001 | active |        1 | 2026-03-12 16:10:29.880642+00 | 2026-03-12 16:10:29.880642+00
 278770300000001 | aaaaaaaa-0003-0000-0000-000000000001 | active |        1 | 2026-03-12 16:10:29.880642+00 | 2026-03-12 16:10:29.880642+00
(3 rows)

aaa=# SELECT * FROM subscriber_profiles;
              device_id               |        iccid        | account_name | status | ip_resolution | metadata |          created_at           |          updated_at
--------------------------------------+---------------------+--------------+--------+---------------+----------+-------------------------------+-------------------------------
 aaaaaaaa-0002-0000-0000-000000000001 | 8944501020000000001 | TestAccount  | active | imsi          |          | 2026-03-12 16:10:29.880642+00 | 2026-03-12 16:10:29.880642+00
 aaaaaaaa-0001-0000-0000-000000000001 | 8944501010000000001 | TestAccount  | active | iccid         |          | 2026-03-12 16:10:29.880642+00 | 2026-03-12 16:10:29.880642+00
 aaaaaaaa-0003-0000-0000-000000000001 | 8944501030000000001 | TestAccount  | active | imsi_apn      |          | 2026-03-12 16:10:29.880642+00 | 2026-03-12 16:10:29.880642+00
(3 rows)