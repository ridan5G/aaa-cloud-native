/**
 * Smoke test — 1 VU, 1 minute.
 * Goal: verify the service is reachable and the happy path returns a valid IP.
 */
import http from 'k6/http';
import { check } from 'k6';
import { Rate } from 'k6/metrics';
import { BASE_URL, randomIMSI, randomAPN, lookupHeaders, SLA_THRESHOLDS } from './common.js';

export const options = {
  vus: 1,
  duration: '1m',
  thresholds: SLA_THRESHOLDS,
  summaryTrendStats: ['min', 'med', 'avg', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

const serverErrors = new Rate('server_errors');

export default function () {
  const imsi = randomIMSI();
  const apn  = randomAPN();
  const url  = `${BASE_URL}/v1/lookup?imsi=${imsi}&apn=${apn}`;

  const res = http.get(url, { headers: lookupHeaders() });

  serverErrors.add(res.status >= 500);

  check(res, {
    'status is 200':        (r) => r.status === 200,
    'has static_ip field':  (r) => r.json('static_ip') !== undefined,
    'response within 15ms': (r) => r.timings.duration < 15,
  });
}
