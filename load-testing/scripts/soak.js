/**
 * Soak test — constant 300 RPS for 45 minutes.
 *
 * Goal: detect memory leaks, connection-pool exhaustion, or
 * gradual latency drift that only appear under sustained load.
 *
 * Pass criteria: same SLA thresholds as load.js held for the full duration.
 * While running, watch:
 *   - aaa_in_flight_requests (should be stable, not growing)
 *   - DB connection pool utilisation via PgBouncer stats
 *   - Pod memory (kubectl top pods -n aaa-platform)
 */
import http from 'k6/http';
import { check } from 'k6';
import { Rate, Trend } from 'k6/metrics';
import { BASE_URL, randomIMSI, randomAPN, lookupHeaders, SLA_THRESHOLDS } from './common.js';

export const options = {
  scenarios: {
    lookup_soak: {
      executor:        'constant-arrival-rate',
      rate:            300,
      timeUnit:        '1s',
      duration:        '45m',
      preAllocatedVUs: 30,
      maxVUs:          100,
    },
  },
  thresholds: SLA_THRESHOLDS,
  summaryTrendStats: ['min', 'med', 'avg', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

const serverErrors = new Rate('server_errors');
const latencyOverTime = new Trend('latency_over_time', true);

export default function () {
  const imsi = randomIMSI();
  const apn  = randomAPN();
  const url  = `${BASE_URL}/v1/lookup?imsi=${imsi}&apn=${apn}`;

  const res = http.get(url, {
    headers: lookupHeaders(),
    tags: { scenario: 'soak' },
  });

  serverErrors.add(res.status >= 500);
  latencyOverTime.add(res.timings.duration);

  check(res, {
    'status 200 or 404':    (r) => r.status === 200 || r.status === 404,
    'no server error':      (r) => r.status < 500,
    'response within 50ms': (r) => r.timings.duration < 50,
  });
}
