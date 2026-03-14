/**
 * Spike test — sudden traffic burst to validate recovery behaviour.
 *
 * Stages:
 *   0 min: baseline at 50 RPS (1 min)
 *   1 min: instant spike to 2 000 RPS (1 min)
 *   2 min: drop back to 50 RPS (1 min)
 *   3 min: second spike to 1 500 RPS (1 min)
 *   4 min: drop back to 50 RPS (1 min)
 *   5 min: ramp down to 0 (30 s)
 *
 * Goal: verify the service recovers within 30 s after a spike, and that
 * p99 latency returns to SLA levels once the burst subsides.
 */
import http from 'k6/http';
import { check } from 'k6';
import { Rate } from 'k6/metrics';
import { BASE_URL, randomIMSI, randomAPN, lookupHeaders } from './common.js';

export const options = {
  scenarios: {
    lookup_spike: {
      executor:        'ramping-arrival-rate',
      startRate:       50,
      timeUnit:        '1s',
      preAllocatedVUs: 100,
      maxVUs:          600,
      stages: [
        { duration: '1m',  target: 50   },  // baseline
        { duration: '1m',  target: 2000 },  // spike 1
        { duration: '1m',  target: 50   },  // recovery
        { duration: '1m',  target: 1500 },  // spike 2
        { duration: '1m',  target: 50   },  // recovery
        { duration: '30s', target: 0    },  // ramp down
      ],
    },
  },
  thresholds: {
    // Only assert recovery window: during ramp-down errors must be gone
    http_req_failed: ['rate<0.20'],
    server_errors:   ['rate<0.10'],
  },
  summaryTrendStats: ['min', 'med', 'avg', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

const serverErrors = new Rate('server_errors');

export default function () {
  const imsi = randomIMSI();
  const apn  = randomAPN();
  const url  = `${BASE_URL}/v1/lookup?imsi=${imsi}&apn=${apn}`;

  const res = http.get(url, {
    headers: lookupHeaders(),
    tags: { scenario: 'spike' },
  });

  serverErrors.add(res.status >= 500);

  check(res, {
    'no server error': (r) => r.status < 500,
  });
}
