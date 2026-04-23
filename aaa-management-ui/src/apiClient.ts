import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios'
import { config } from './config'

// In-memory token store — never persisted to localStorage/cookies
let accessToken: string | null = null
export const setAccessToken = (t: string | null) => { accessToken = t }
export const getAccessToken = () => accessToken

export const apiClient = axios.create({
  baseURL: config.apiBaseUrl,
})

apiClient.interceptors.request.use(cfg => {
  if (accessToken) {
    cfg.headers.Authorization = `Bearer ${accessToken}`
  }
  return cfg
})

// ---------------------------------------------------------------------------
// RUM (Real User Monitoring) metrics
// ---------------------------------------------------------------------------
// In-memory bucket: endpoint template → { count, totalMs, errors }
type RumBucket = { count: number; totalMs: number; errors: number }
const rumBuckets = new Map<string, RumBucket>()

// Collapse dynamic path segments so "/profiles/abc-123" → "/profiles/:id"
function templatePath(url: string): string {
  return url
    .replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi, ':id')
    .replace(/\/\d+/g, '/:id')
}

function recordRum(url: string, durationMs: number, isError: boolean) {
  const key = templatePath(url)
  const b = rumBuckets.get(key) ?? { count: 0, totalMs: 0, errors: 0 }
  b.count += 1
  b.totalMs += durationMs
  if (isError) b.errors += 1
  rumBuckets.set(key, b)
}

// Expose aggregated snapshot (used by optional flush below)
export function getRumSnapshot(): Record<string, RumBucket> {
  return Object.fromEntries(rumBuckets)
}

// Flush to Prometheus Pushgateway if APP_CONFIG.pushgatewayUrl is set.
// Called automatically every 30 s. Safe to call manually (e.g. on page unload).
export async function flushRumMetrics(): Promise<void> {
  const gw: string | undefined = (window as Window & { APP_CONFIG?: Record<string, string> })
    .APP_CONFIG?.pushgatewayUrl
  if (!gw || rumBuckets.size === 0) return

  // Build Prometheus text-format payload
  const lines: string[] = [
    '# HELP ui_api_call_duration_ms_total Total milliseconds spent in API calls by endpoint',
    '# TYPE ui_api_call_duration_ms_total counter',
    '# HELP ui_api_call_requests_total Total API calls by endpoint',
    '# TYPE ui_api_call_requests_total counter',
    '# HELP ui_api_call_errors_total Total API call errors by endpoint',
    '# TYPE ui_api_call_errors_total counter',
  ]
  for (const [endpoint, b] of rumBuckets) {
    const lbl = `{endpoint="${endpoint}"}`
    lines.push(`ui_api_call_duration_ms_total${lbl} ${b.totalMs.toFixed(2)}`)
    lines.push(`ui_api_call_requests_total${lbl} ${b.count}`)
    lines.push(`ui_api_call_errors_total${lbl} ${b.errors}`)
  }

  try {
    await fetch(`${gw}/metrics/job/aaa-management-ui`, {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain; version=0.0.4' },
      body: lines.join('\n') + '\n',
    })
  } catch {
    // Silently ignore — metrics are best-effort
  }
}

// Periodic auto-flush (30 s interval, only if pushgateway is configured)
if (typeof window !== 'undefined') {
  setInterval(flushRumMetrics, 30_000)
  window.addEventListener('beforeunload', () => { void flushRumMetrics() })
}

// ---------------------------------------------------------------------------
// API error extraction — pulls a human-readable reason from structured 4xx bodies
// ---------------------------------------------------------------------------
function extractApiReason(data: unknown): string | null {
  if (!data || typeof data !== 'object') return null
  const d = data as Record<string, unknown>
  // {error: "validation_failed", details: [{field, message}, ...]}
  if (Array.isArray(d.details) && d.details.length > 0) {
    const msg = (d.details as Array<Record<string, unknown>>)
      .filter(e => e.message)
      .map(e => e.field ? `${e.field}: ${e.message}` : String(e.message))
      .join('; ')
    if (msg) return msg
  }
  // {detail: "plain string"}
  if (typeof d.detail === 'string') return d.detail
  // {error: "pool_exhausted"} — humanise the code as last resort
  if (typeof d.error === 'string') return d.error.replace(/_/g, ' ')
  return null
}

// ---------------------------------------------------------------------------
// Request timing interceptor — stamps _t0 on every outgoing request
// ---------------------------------------------------------------------------
type TimedConfig = InternalAxiosRequestConfig & { _t0?: number }

apiClient.interceptors.request.use((cfg: TimedConfig) => {
  cfg._t0 = performance.now()
  return cfg
})

// ---------------------------------------------------------------------------
// Response interceptor — records timing + auto-retry on 429
// ---------------------------------------------------------------------------
apiClient.interceptors.response.use(
  res => {
    const cfg = res.config as TimedConfig
    if (cfg._t0 !== undefined && cfg.url) {
      recordRum(cfg.url, performance.now() - cfg._t0, false)
    }
    return res
  },
  async (err: AxiosError) => {
    const cfg = err.config as (TimedConfig & { _retryCount?: number }) | undefined
    if (!cfg) return Promise.reject(err)

    // Record timing for non-429 errors (429 will be retried below)
    if (err.response?.status !== 429 && cfg._t0 !== undefined && cfg.url) {
      recordRum(cfg.url, performance.now() - cfg._t0, true)
    }

    if (err.response?.status !== 429) {
      if (err.response && err.response.status >= 400) {
        const reason = extractApiReason(err.response.data)
        if (reason) err.message = reason
      }
      return Promise.reject(err)
    }

    cfg._retryCount = (cfg._retryCount ?? 0) + 1
    if (cfg._retryCount > 3) return Promise.reject(err)

    const delay = 500 * 2 ** (cfg._retryCount - 1)
    await new Promise(r => setTimeout(r, delay))
    return apiClient(cfg)
  },
)
