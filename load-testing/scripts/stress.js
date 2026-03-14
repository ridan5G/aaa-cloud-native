/**
 * Stress test — find the breaking point by incrementally increasing RPS.
 *
 * Stages:
 *   0 →  200 RPS  (3 min)
 *   200 → 500 RPS  (3 min)
 *   500 → 1000 RPS (3 min)
 *   1000 → 1500 RPS (3 min)
 *   1500 → 2000 RPS (3 min)
 *   2000 RPS        (5 min sustain)
 *   2000 →    0 RPS (5 min cooldown)
 *
 * Thresholds are relaxed — the goal is to observe where latency and
 * error rate degrade, not to enforce strict SLA.  Watch Prometheus
 * aaa_lookup_duration_seconds and aaa_lookup_requests_total{result="db_error"}.
 */
import http from 'k6/http';
import { check } from 'k6';
import { Rate, Trend } from 'k6/metrics';
import { BASE_URL, randomIMSI, randomAPN, lookupHeaders, STRESS_THRESHOLDS } from './common.js';

export const options = {
  scenarios: {
    lookup_stress: {
      executor:        'ramping-arrival-rate',
      startRate:       0,
      timeUnit:        '1s',
      preAllocatedVUs: 100,
      maxVUs:          500,
      stages: [
        { duration: '3m', target: 200  },
        { duration: '3m', target: 500  },
        { duration: '3m', target: 1000 },
        { duration: '3m', target: 1500 },
        { duration: '3m', target: 2000 },
        { duration: '5m', target: 2000 },
        { duration: '5m', target: 0    },
      ],
    },
  },
  thresholds: STRESS_THRESHOLDS,
  summaryTrendStats: ['min', 'med', 'avg', 'p(90)', 'p(95)', 'p(99)', 'p(99.9)', 'max'],
};

const serverErrors = new Rate('server_errors');
const lookupOkDuration = new Trend('lookup_ok_duration', true);  // true = in ms

export default function () {
  const imsi = randomIMSI();
  const apn  = randomAPN();
  const url  = `${BASE_URL}/v1/lookup?imsi=${imsi}&apn=${apn}`;

  const res = http.get(url, {
    headers: lookupHeaders(),
    tags: { scenario: 'stress' },
  });

  serverErrors.add(res.status >= 500);

  if (res.status === 200) {
    lookupOkDuration.add(res.timings.duration);
  }

  check(res, {
    'no server error': (r) => r.status < 500,
  });
}
