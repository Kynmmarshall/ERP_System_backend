// k6 load test against the LOCAL docker-compose stack's gateway
// (http://localhost:8081) - never point this at the real production VPS.
//
// Scope/disclosure: plan.md's target is 25 concurrent sessions for 5
// minutes. This script defaults to a shorter, clearly-labeled smoke
// profile (25 VUs for 60s) suitable for a single dev machine also running
// Docker Desktop and every service under test - override via the
// SMOKE_DURATION/SMOKE_VUS env vars for a longer run. Report whichever
// duration/VUs were actually used, never silently claim the full target
// ran.
//
// Login happens exactly ONCE in setup() (not per-VU/per-iteration) and
// the resulting access token is shared read-only by every VU: the
// gateway's login rate limit is a strict 5 requests/minute per source IP
// (gateway/nginx.conf), which many concurrent logins would immediately
// trip. This test measures ordinary authenticated CRUD READ latency
// (plan.md's target), not the login endpoint itself.
import http from 'k6/http'
import { check } from 'k6'

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8081'
const ADMIN_EMAIL = __ENV.ADMIN_EMAIL || 'admin@ictuniversity.example'
const ADMIN_PASSWORD = __ENV.ADMIN_PASSWORD || ''

export const options = {
  scenarios: {
    smoke: {
      executor: 'constant-vus',
      vus: Number(__ENV.SMOKE_VUS || 25),
      duration: __ENV.SMOKE_DURATION || '60s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    // Applied only to the read requests (tagged below), excluding the
    // one-time setup login and excluding any external-provider call
    // (there are none in this scenario) per plan.md's carve-out.
    'http_req_duration{kind:read}': ['p(95)<500'],
  },
}

export function setup() {
  if (!ADMIN_PASSWORD) {
    throw new Error('Set ADMIN_PASSWORD to the seeded admin account password before running this script')
  }
  const loginRes = http.post(
    `${BASE_URL}/api/v1/auth/login`,
    JSON.stringify({ email: ADMIN_EMAIL, password: ADMIN_PASSWORD }),
    { headers: { 'Content-Type': 'application/json' } },
  )
  check(loginRes, { 'login succeeded': (r) => r.status === 200 })
  const token = loginRes.json('access_token')
  return { token }
}

export default function (data) {
  const headers = { Authorization: `Bearer ${data.token}` }

  const reads = [
    ['GET', `${BASE_URL}/api/v1/academic/programs`],
    ['GET', `${BASE_URL}/api/v1/academic/terms`],
    ['GET', `${BASE_URL}/api/v1/finance/expenses`],
    ['GET', `${BASE_URL}/api/v1/hr/positions`],
  ]

  for (const [, url] of reads) {
    const res = http.get(url, { headers, tags: { kind: 'read' } })
    check(res, { 'read succeeded': (r) => r.status === 200 })
  }
}
