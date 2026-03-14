/**
 * Shared configuration and helpers for all aaa-lookup k6 test scripts.
 */
import { SharedArray } from 'k6/data';

export const BASE_URL    = __ENV.TARGET_URL    || 'http://localhost:8081';
export const BEARER_TOKEN = __ENV.BEARER_TOKEN || 'dev-load-test';
export const IMSI_COUNT   = parseInt(__ENV.IMSI_COUNT || '10000');

// APNs to exercise — matches seed data
export const APNS = ['internet', 'mms', 'ims'];

// Pre-build IMSI list once, shared across all VUs.
// Range: 001010000001001 – 001010000011000
const _imsis = new SharedArray('imsis', function () {
  const arr = [];
  for (let i = 1; i <= IMSI_COUNT; i++) {
    // 1010000000000 + i, zero-padded to 15 digits
    arr.push(String(1010000000000 + i).padStart(15, '0'));
  }
  return arr;
});

export function randomIMSI() {
  return _imsis[Math.floor(Math.random() * _imsis.length)];
}

export function randomAPN() {
  return APNS[Math.floor(Math.random() * APNS.length)];
}

export function lookupHeaders() {
  return { Authorization: `Bearer ${BEARER_TOKEN}` };
}

// ── Standard thresholds reflecting the <15 ms p99 SLA ───────────────────────
export const SLA_THRESHOLDS = {
  http_req_duration:                        ['p(95)<10', 'p(99)<15'],
  'http_req_duration{expected_response:true}': ['p(99)<15'],
  http_req_failed:                          ['rate<0.005'],
  server_errors:                            ['rate<0.001'],
};

// Relaxed thresholds for stress / spike (goal: observe, not fail the run early)
export const STRESS_THRESHOLDS = {
  http_req_duration:  ['p(99)<100'],
  http_req_failed:    ['rate<0.15'],
  server_errors:      ['rate<0.05'],
};
