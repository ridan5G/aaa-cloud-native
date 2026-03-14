/**
 * Load test — ramping arrival-rate, target 500 RPS, 14 minutes total.
 *
 * Stages:
 *   0 →  200 RPS  (2 min ramp-up)
 *   200 → 500 RPS (4 min ramp-up)
 *   500 RPS        (6 min sustain)
 *   500 →   0 RPS (2 min ramp-down)
 *
 * Pass criteria: p95 < 10 ms, p99 < 15 ms, error rate < 0.5 %.
 */
import http from 'k6/http';
import { check } from 'k6';
import { Rate } from 'k6/metrics';
import { BASE_URL, randomIMSI, randomAPN, lookupHeaders, SLA_THRESHOLDS } from './common.js';

export const options = {
  scenarios: {
    lookup_load: {
      executor:        'ramping-arrival-rate',
      startRate:       0,
      timeUnit:        '1s',
      preAllocatedVUs: 50,
      maxVUs:          200,
      stages: [
        { duration: '2m', target: 200 },
        { duration: '4m', target: 500 },
        { duration: '6m', target: 500 },
        { duration: '2m', target: 0   },
      ],
    },
  },
  thresholds: SLA_THRESHOLDS,
  summaryTrendStats: ['min', 'med', 'avg', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

const serverErrors = new Rate('server_errors');

export default function () {
  const imsi = randomIMSI();
  const apn  = randomAPN();
  const url  = `${BASE_URL}/v1/lookup?imsi=${imsi}&apn=${apn}`;

  const res = http.get(url, {
    headers: lookupHeaders(),
    tags: { scenario: 'load' },
  });

  serverErrors.add(res.status >= 500);

  check(res, {
    'status 200 or 404':    (r) => r.status === 200 || r.status === 404,
    'no server error':      (r) => r.status < 500,
    'response within 50ms': (r) => r.timings.duration < 50,
  });
}
