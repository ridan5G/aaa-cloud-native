import { useEffect, useRef, useState } from 'react'
import { Routes, Route, useNavigate, useParams } from 'react-router-dom'
import { apiClient } from '../apiClient'
import StatusBadge from '../components/StatusBadge'
import { useToasts } from '../stores/toast'
import type { Pool, PoolStats, RoutingDomain, SuggestCidrResult } from '../types'

function poolBarColor(pct: number) {
  if (pct > 90) return '#E53E3E'
  if (pct > 75) return '#E07B39'
  return '#F5A623'
}

// ─── Domain Combo Box ─────────────────────────────────────────────────────────
/**
 * Searchable combo box for selecting a routing domain.
 * - `includeAll`   — prepends an "All domains" option (value = '')
 * - `allowFreeText`— lets the user type an arbitrary name (auto-create on save)
 * - `error`        — highlights input border red
 */
function DomainComboBox({
  domains,
  value,
  onChange,
  placeholder = 'Search domains…',
  allowFreeText = false,
  includeAll = false,
  error = false,
}: {
  domains: RoutingDomain[]
  value: string
  onChange: (name: string) => void
  placeholder?: string
  allowFreeText?: boolean
  includeAll?: boolean
  error?: boolean
}) {
  const [open,  setOpen]  = useState(false)
  const [query, setQuery] = useState(value)
  const ref = useRef<HTMLDivElement>(null)

  // Keep display text in sync when value changes externally
  useEffect(() => { setQuery(value) }, [value])

  // Close on outside click; if free-text not allowed, reset to last committed value
  useEffect(() => {
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
        if (!allowFreeText) setQuery(value)
      }
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [value, allowFreeText])

  // Only filter when query differs from selected value (so full list shows after selection)
  const filtered =
    query.trim() === '' || query === value
      ? domains
      : domains.filter(d => d.name.toLowerCase().includes(query.toLowerCase()))

  function select(name: string) {
    onChange(name)
    setQuery(name)
    setOpen(false)
  }

  return (
    <div ref={ref} className="relative">
      {/* Input row */}
      <div className={`flex items-center border rounded-md bg-white overflow-hidden transition-shadow ${
        error
          ? 'border-red-400 focus-within:ring-2 focus-within:ring-red-300'
          : 'border-border focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/20'
      }`}>
        <input
          className="flex-1 px-3 py-2 text-sm bg-transparent outline-none font-mono placeholder-gray-400"
          placeholder={placeholder}
          value={query}
          onFocus={() => setOpen(true)}
          onChange={e => {
            setQuery(e.target.value)
            if (allowFreeText) onChange(e.target.value)
            setOpen(true)
          }}
          onKeyDown={e => {
            if (e.key === 'Escape') { setOpen(false); if (!allowFreeText) setQuery(value) }
            if (e.key === 'Enter' && filtered.length > 0) { e.preventDefault(); select(filtered[0].name) }
          }}
        />
        {/* Clear button */}
        {value && !includeAll && (
          <button
            type="button"
            className="px-1.5 text-gray-300 hover:text-gray-500 transition-colors"
            onClick={() => { select(''); setQuery('') }}
            tabIndex={-1}
          >
            <svg viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.8" className="w-3 h-3">
              <path d="M2 2l6 6M8 2l-6 6" />
            </svg>
          </button>
        )}
        {/* Chevron toggle */}
        <button
          type="button"
          className="px-2.5 text-gray-400 hover:text-gray-600 transition-colors"
          onClick={() => setOpen(o => !o)}
          tabIndex={-1}
        >
          <svg viewBox="0 0 10 6" fill="none" stroke="currentColor" strokeWidth="1.5" className="w-2.5 h-2.5">
            <path d={open ? 'M1 5l4-4 4 4' : 'M1 1l4 4 4-4'} />
          </svg>
        </button>
      </div>

      {/* Dropdown panel */}
      {open && (
        <div className="absolute z-50 mt-1 w-full rounded-lg border border-border bg-white shadow-lg max-h-60 overflow-y-auto">
          {/* "All domains" sentinel */}
          {includeAll && (
            <button
              type="button"
              className={`w-full text-left px-3 py-2 text-sm transition-colors hover:bg-page ${
                value === '' ? 'bg-primary/5 text-primary font-medium' : 'text-gray-500'
              }`}
              onClick={() => select('')}
            >
              All domains
            </button>
          )}

          {/* Empty-state messages */}
          {filtered.length === 0 && !allowFreeText && (
            <div className="px-3 py-2.5 text-xs text-gray-400">No matching domains</div>
          )}
          {filtered.length === 0 && allowFreeText && query && (
            <div className="px-3 py-2.5 text-xs text-gray-500">
              Press Enter or click away to use{' '}
              <span className="font-mono font-semibold text-gray-700">&ldquo;{query}&rdquo;</span>
              {' '}— will be auto-created.
            </div>
          )}

          {/* Domain options */}
          {filtered.map(d => (
            <button
              key={d.id}
              type="button"
              className={`w-full text-left px-3 py-2 text-sm transition-colors hover:bg-page flex items-baseline gap-2 ${
                value === d.name ? 'bg-primary/5 text-primary font-medium' : 'text-gray-700'
              }`}
              onClick={() => select(d.name)}
            >
              <span className="font-mono">{d.name}</span>
              {d.description && (
                <span className="text-xs text-gray-400 truncate">{d.description}</span>
              )}
              {(d.allowed_prefixes?.length ?? 0) > 0 && (
                <span className="ml-auto text-xs text-blue-500 shrink-0">
                  {d.allowed_prefixes.length} prefix{d.allowed_prefixes.length > 1 ? 'es' : ''}
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Pool List ────────────────────────────────────────────────────────────────
function PoolList() {
  const navigate  = useNavigate()
  const { show }  = useToasts()
  const [pools,          setPools]          = useState<(Pool & PoolStats)[]>([])
  const [loading,        setLoading]        = useState(true)
  const [error,          setError]          = useState<string | null>(null)
  const [showNew,        setShowNew]        = useState(false)
  const [routingDomains, setRoutingDomains] = useState<RoutingDomain[]>([])
  const [domainFilter,   setDomainFilter]   = useState('')

  // ── Free CIDR Finder ──────────────────────────────────────────────────────
  const [cidrDomain,     setCidrDomain]     = useState('')
  const [cidrSize,       setCidrSize]       = useState('')
  const [cidrSuggesting, setCidrSuggesting] = useState(false)
  const [cidrSuggestion, setCidrSuggestion] = useState<SuggestCidrResult | null>(null)
  const [cidrError,      setCidrError]      = useState<string | null>(null)

  // Pre-fill values passed into NewPoolModal when "Create Pool" is clicked
  const [prefillDomain, setPrefillDomain] = useState<string | undefined>()
  const [prefillSubnet, setPrefillSubnet] = useState<string | undefined>()

  const cidrSelectedDomain = routingDomains.find(d => d.name === cidrDomain)
  const cidrCanSuggest     = !!cidrSelectedDomain && cidrSelectedDomain.allowed_prefixes.length > 0

  async function handleCidrSuggest() {
    if (!cidrSelectedDomain || !cidrSize) return
    const size = parseInt(cidrSize, 10)
    if (isNaN(size) || size < 1) { setCidrError('Enter a valid number ≥ 1'); return }
    setCidrSuggesting(true); setCidrSuggestion(null); setCidrError(null)
    try {
      const res = await apiClient.get(`/routing-domains/${cidrSelectedDomain.id}/suggest-cidr`, { params: { size } })
      setCidrSuggestion(res.data)
    } catch (e: unknown) {
      const raw = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      const msg: string = typeof raw === 'string' ? raw
        : (raw as { detail?: string; error?: string } | undefined)?.detail
          ?? (raw as { detail?: string; error?: string } | undefined)?.error
          ?? String(e)
      setCidrError(msg)
    } finally { setCidrSuggesting(false) }
  }

  function handleCreateFromSuggestion() {
    if (!cidrSuggestion || !cidrSelectedDomain) return
    setPrefillDomain(cidrSelectedDomain.name)
    setPrefillSubnet(cidrSuggestion.suggested_cidr)
    setShowNew(true)
  }

  function closeModal() {
    setShowNew(false)
    setPrefillDomain(undefined)
    setPrefillSubnet(undefined)
  }

  async function load() {
    setLoading(true)
    try {
      const params: Record<string, string> = {}
      if (domainFilter) params.routing_domain = domainFilter
      const res = await apiClient.get('/pools', { params })
      const list: Pool[] = res.data.pools ?? res.data.items ?? []
      const enriched = await Promise.all(
        list.map(async p => {
          try {
            const s = await apiClient.get(`/pools/${p.pool_id}/stats`)
            return { ...p, ...s.data }
          } catch { return { ...p, total: 0, allocated: 0, available: 0 } }
        })
      )
      setPools(enriched)
    } catch (e) { setError(String(e)) } finally { setLoading(false) }
  }

  async function loadDomains() {
    try {
      const res = await apiClient.get('/routing-domains', { params: { limit: 1000 } })
      setRoutingDomains(res.data.items ?? [])
    } catch { /* non-critical */ }
  }

  useEffect(() => { loadDomains() }, [])
  useEffect(() => { load() }, [domainFilter]) // eslint-disable-line

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs text-gray-400 uppercase tracking-widest font-medium">Networking</p>
          <h1 className="page-title">IP Pools</h1>
        </div>
        <button onClick={() => setShowNew(true)} className="btn-primary">+ New Pool</button>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-3">
        <label className="text-xs text-gray-500 font-medium whitespace-nowrap">Routing Domain</label>
        <div className="w-64">
          <DomainComboBox
            domains={routingDomains}
            value={domainFilter}
            onChange={setDomainFilter}
            placeholder="All domains"
            includeAll
          />
        </div>
      </div>

      {error && <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-lg">{error}</div>}

      {/* Free CIDR Finder */}
      <div className="card p-5 space-y-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-800">Free CIDR Finder</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            Find an available subnet in a routing domain and create a pool directly from the result.
            The routing domain must have <code className="font-mono">allowed_prefixes</code> configured.
          </p>
        </div>
        <div className="flex items-end gap-3 flex-wrap">
          <div className="field mb-0 w-56">
            <label className="label">Routing Domain</label>
            <DomainComboBox
              domains={routingDomains}
              value={cidrDomain}
              onChange={v => { setCidrDomain(v); setCidrSuggestion(null); setCidrError(null) }}
              placeholder="Select domain…"
            />
            {cidrSelectedDomain && !cidrSelectedDomain.allowed_prefixes.length && (
              <p className="text-xs text-amber-600 mt-1">
                ⚠ This domain has no allowed_prefixes — configure them first to enable CIDR suggestion.
              </p>
            )}
          </div>
          <div className="field mb-0 w-36">
            <label className="label">Min hosts needed *</label>
            <input
              className="input font-mono"
              type="number"
              min={1}
              placeholder="e.g. 254"
              value={cidrSize}
              onChange={e => { setCidrSize(e.target.value); setCidrSuggestion(null); setCidrError(null) }}
              onKeyDown={e => { if (e.key === 'Enter') handleCidrSuggest() }}
            />
          </div>
          <button
            onClick={handleCidrSuggest}
            disabled={!cidrCanSuggest || !cidrSize || cidrSuggesting}
            className="btn-primary"
            title={cidrSelectedDomain && !cidrSelectedDomain.allowed_prefixes.length ? 'Configure allowed_prefixes on this domain first' : ''}
          >
            {cidrSuggesting ? 'Searching…' : 'Find Free CIDR'}
          </button>
        </div>
        {cidrError && (
          <div className="flex gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-xs text-red-700">
            <span className="shrink-0 mt-0.5">✕</span>
            <span>{cidrError}</span>
          </div>
        )}
        {cidrSuggestion && (
          <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 flex items-center gap-4 flex-wrap">
            <div className="space-y-0.5 flex-1 min-w-0">
              <p className="text-xs font-semibold text-green-700 uppercase tracking-wide">Suggested</p>
              <div className="flex items-center gap-3 flex-wrap">
                <code className="text-base font-mono font-bold text-green-800">{cidrSuggestion.suggested_cidr}</code>
                <span className="text-xs text-green-600">
                  /{cidrSuggestion.prefix_len} · {cidrSuggestion.usable_hosts.toLocaleString()} usable hosts · no overlap in "{cidrSuggestion.routing_domain_name}"
                </span>
              </div>
            </div>
            <div className="flex gap-2 shrink-0">
              <button
                onClick={() => { navigator.clipboard.writeText(cidrSuggestion!.suggested_cidr); show('info', 'Copied to clipboard') }}
                className="btn-ghost text-xs py-1.5 px-3"
              >
                Copy
              </button>
              <button onClick={handleCreateFromSuggestion} className="btn-primary text-xs py-1.5 px-3">
                Create Pool
              </button>
            </div>
          </div>
        )}
      </div>

      {showNew && (
        <NewPoolModal
          routingDomains={routingDomains}
          initialDomain={prefillDomain}
          initialSubnet={prefillSubnet}
          onClose={closeModal}
          onSuccess={() => { closeModal(); load(); loadDomains() }}
        />
      )}

      <div className="tbl-wrap">
        {loading ? (
          <div className="flex items-center justify-center h-40 text-gray-400 text-sm">Loading…</div>
        ) : pools.length === 0 ? (
          <div className="flex items-center justify-center h-40 text-gray-400 text-sm">No pools configured.</div>
        ) : (
          <table className="tbl">
            <thead><tr>
              <th>Pool Name</th><th>Routing Domain</th><th>Subnet</th><th>Utilization</th>
              <th className="text-right">Total</th><th className="text-right">Allocated</th><th className="text-right">Available</th>
              <th>Status</th><th />
            </tr></thead>
            <tbody>
              {pools.map(p => {
                const pct = p.total > 0 ? Math.round((p.allocated / p.total) * 100) : 0
                return (
                  <tr key={p.pool_id}
                    className="border-b border-border hover:bg-page transition-colors cursor-pointer"
                    onClick={() => navigate(p.pool_id)}>
                    <td className="px-4 py-3 font-medium text-sm">{p.name}</td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700 ring-1 ring-blue-200">
                        {p.routing_domain ?? 'default'}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-600">{p.subnet}</td>
                    <td className="px-4 py-3 w-40">
                      <div className="flex items-center gap-2">
                        <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                          <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: poolBarColor(pct) }} />
                        </div>
                        <span className="text-xs text-gray-500 tabular-nums w-8 text-right">{pct}%</span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-sm text-right tabular-nums">{(p.total ?? 0).toLocaleString()}</td>
                    <td className="px-4 py-3 text-sm text-right tabular-nums">{(p.allocated ?? 0).toLocaleString()}</td>
                    <td className="px-4 py-3 text-sm text-right tabular-nums text-green-700">{(p.available ?? 0).toLocaleString()}</td>
                    <td className="px-4 py-3"><StatusBadge status={p.status} /></td>
                    <td className="px-4 py-3 text-right"><span className="text-xs text-primary">View →</span></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

// ─── Pool Detail ──────────────────────────────────────────────────────────────
function PoolDetail() {
  const { pool_id } = useParams<{ pool_id: string }>()
  const navigate    = useNavigate()
  const { show }    = useToasts()
  const [pool,    setPool]    = useState<Pool | null>(null)
  const [stats,   setStats]   = useState<PoolStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [newName, setNewName] = useState('')

  async function load() {
    if (!pool_id) return; setLoading(true)
    try {
      const [pr, sr] = await Promise.all([
        apiClient.get(`/pools/${pool_id}`),
        apiClient.get(`/pools/${pool_id}/stats`),
      ])
      setPool(pr.data); setStats(sr.data)
    } catch (e) { setError(String(e)) } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [pool_id]) // eslint-disable-line

  async function saveEdit() {
    try { await apiClient.patch(`/pools/${pool_id}`, { name: newName }); show('success', 'Pool updated'); setEditing(false); load() }
    catch (e) { show('error', String(e)) }
  }

  async function deletePool() {
    if (!stats || stats.allocated > 0) { show('error', 'Cannot delete pool with allocated IPs'); return }
    if (!confirm('Delete this pool?')) return
    try { await apiClient.delete(`/pools/${pool_id}`); show('success', 'Pool deleted'); navigate('/pools') }
    catch (e) { show('error', String(e)) }
  }

  if (loading) return <div className="flex items-center justify-center h-60 text-gray-400 text-sm">Loading…</div>
  if (error)   return <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">{error}</div>
  if (!pool)   return null

  const pct = stats && stats.total > 0 ? Math.round((stats.allocated / stats.total) * 100) : 0

  return (
    <div className="space-y-4 max-w-3xl">
      <div className="flex items-center gap-2 text-sm">
        <button onClick={() => navigate('/pools')} className="text-primary hover:underline">IP Pools</button>
        <span className="text-gray-400">/</span>
        <span className="text-gray-600">{pool.name}</span>
      </div>

      <div className="card p-6 space-y-5">
        <div className="flex items-start justify-between">
          <div>
            {editing ? (
              <div className="flex items-center gap-2">
                <input className="input text-sm font-medium" value={newName} onChange={e => setNewName(e.target.value)} />
                <button onClick={saveEdit} className="btn-primary text-xs py-1.5 px-3">Save</button>
                <button onClick={() => setEditing(false)} className="btn-ghost text-xs">Cancel</button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-semibold text-gray-900">{pool.name}</h2>
                <button onClick={() => { setNewName(pool.name); setEditing(true) }} className="text-xs text-gray-400 hover:text-gray-600">Edit</button>
              </div>
            )}
            <p className="font-mono text-xs text-gray-400 mt-0.5">{pool.pool_id}</p>
          </div>
          <div className="flex gap-2">
            <StatusBadge status={pool.status} />
            <button onClick={deletePool} className="btn-danger text-xs py-1 px-3"
              title={stats?.allocated ? 'Cannot delete — IPs allocated' : 'Delete pool'}>
              Delete
            </button>
          </div>
        </div>

        {/* Info grid */}
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
          {[
            { l: 'Subnet',         v: pool.subnet   },
            { l: 'Start IP',       v: pool.start_ip },
            { l: 'End IP',         v: pool.end_ip   },
            { l: 'Account',        v: pool.account_name ?? '—' },
          ].map(f => (
            <div key={f.l}>
              <p className="text-xs text-gray-400 uppercase tracking-wide font-medium mb-0.5">{f.l}</p>
              <p className="font-mono text-sm text-gray-800">{f.v}</p>
            </div>
          ))}
          {/* Routing domain — shown as a badge (immutable after creation) */}
          <div>
            <p className="text-xs text-gray-400 uppercase tracking-wide font-medium mb-1">Routing Domain</p>
            <span className="inline-flex items-center rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700 ring-1 ring-blue-200">
              {pool.routing_domain ?? 'default'}
            </span>
            {pool.routing_domain_id && (
              <p className="font-mono text-xs text-gray-400 mt-0.5">{pool.routing_domain_id}</p>
            )}
          </div>
        </div>

        {/* Utilization gauge */}
        {stats && (
          <div className="pt-4 border-t border-border">
            <div className="flex items-center justify-between text-sm mb-2">
              <span className="font-medium text-gray-700">Utilization</span>
              <span className="tabular-nums text-gray-500">
                {stats.allocated.toLocaleString()} / {stats.total.toLocaleString()} IPs ({pct}%)
              </span>
            </div>
            <div className="h-3 bg-gray-100 rounded-full overflow-hidden">
              <div className="h-full rounded-full transition-all"
                style={{ width: `${pct}%`, backgroundColor: poolBarColor(pct) }} />
            </div>
            <div className="grid grid-cols-3 gap-4 mt-4">
              {[
                { l: 'Total',     v: stats.total.toLocaleString(),     cls: '' },
                { l: 'Allocated', v: stats.allocated.toLocaleString(), cls: '' },
                { l: 'Available', v: stats.available.toLocaleString(), cls: 'text-green-700 font-medium' },
              ].map(s => (
                <div key={s.l} className="card p-3 text-center">
                  <p className="text-xs text-gray-400 uppercase tracking-wide">{s.l}</p>
                  <p className={`text-xl font-bold mt-0.5 tabular-nums ${s.cls || 'text-gray-900'}`}>{s.v}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Error shapes returned by the API ─────────────────────────────────────────
interface OverlapError {
  error: 'pool_overlap'
  detail: string
  conflicting_pool_id: string
  conflicting_pool_name?: string
  conflicting_subnet?: string
  routing_domain_name?: string
}

function isValidCidr(s: string): boolean {
  const m = s.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\/(\d{1,2})$/)
  if (!m) return false
  return [m[1], m[2], m[3], m[4]].every(o => Number(o) <= 255) && Number(m[5]) <= 32
}

interface PrefixError {
  error: 'subnet_outside_allowed_prefixes'
  detail: string
  allowed_prefixes: string[]
}

// ─── New Pool Modal ───────────────────────────────────────────────────────────
function NewPoolModal({
  routingDomains,
  initialDomain,
  initialSubnet,
  onClose,
  onSuccess,
}: {
  routingDomains: RoutingDomain[]
  initialDomain?: string
  initialSubnet?: string
  onClose: () => void
  onSuccess: () => void
}) {
  const { show } = useToasts()
  const [form, setForm] = useState({
    name: '', subnet: initialSubnet ?? '', account_name: '', routing_domain: initialDomain ?? 'default',
  })
  const [saving,       setSaving]       = useState(false)
  const [overlapError, setOverlapError] = useState<OverlapError | null>(null)
  const [prefixError,  setPrefixError]  = useState<PrefixError | null>(null)
  const [formError,    setFormError]    = useState<string | null>(null)

  // Suggest-CIDR inline helper
  const [suggestSize,  setSuggestSize]  = useState('')
  const [suggesting,   setSuggesting]   = useState(false)
  const [suggestion,   setSuggestion]   = useState<SuggestCidrResult | null>(null)
  const [suggestError, setSuggestError] = useState<string | null>(null)

  const selectedDomain = routingDomains.find(d => d.name === form.routing_domain)
  const canSuggest = !!selectedDomain && selectedDomain.allowed_prefixes.length > 0

  const setF = (k: string, v: string) => {
    setForm(f => ({ ...f, [k]: v }))
    if (k === 'subnet' || k === 'routing_domain') {
      setOverlapError(null)
      setPrefixError(null)
      setFormError(null)
      setSuggestion(null)
      setSuggestError(null)
    }
  }

  async function handleSuggest() {
    if (!selectedDomain || !suggestSize) return
    const size = parseInt(suggestSize, 10)
    if (isNaN(size) || size < 1) { setSuggestError('Enter a valid number ≥ 1'); return }
    setSuggesting(true)
    setSuggestion(null)
    setSuggestError(null)
    try {
      const res = await apiClient.get(`/routing-domains/${selectedDomain.id}/suggest-cidr`, {
        params: { size },
      })
      setSuggestion(res.data)
      setF('subnet', res.data.suggested_cidr)  // auto-fill subnet field
    } catch (e: unknown) {
      const raw = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      const msg: string = typeof raw === 'string' ? raw
        : (raw as { detail?: string; error?: string } | undefined)?.detail
          ?? (raw as { detail?: string; error?: string } | undefined)?.error
          ?? String(e)
      setSuggestError(msg)
    } finally { setSuggesting(false) }
  }

  async function handleCreate() {
    if (!isValidCidr(form.subnet)) {
      setFormError('Invalid subnet — enter a valid CIDR block (e.g. 100.64.0.0/24)')
      return
    }
    setSaving(true)
    setOverlapError(null)
    setPrefixError(null)
    setFormError(null)
    try {
      await apiClient.post('/pools', {
        name:         form.name,
        subnet:       form.subnet,
        account_name: form.account_name || undefined,
        // Prefer UUID when domain was selected from the list; fall back to name (auto-create path)
        ...(selectedDomain
          ? { routing_domain_id: selectedDomain.id }
          : { routing_domain: form.routing_domain || 'default' }
        ),
      })
      const usable = suggestion?.usable_hosts
      show('success', usable ? `Pool created — ${usable.toLocaleString()} IPs now available` : 'Pool created')
      onSuccess()
    } catch (err: unknown) {
      const resp = (err as { response?: { status: number; data: unknown } })?.response
      if (resp?.status === 409) {
        const data = resp.data as Record<string, unknown>
        if (data?.error === 'pool_overlap') {
          setOverlapError(data as unknown as OverlapError)
          return
        }
        if (data?.error === 'subnet_outside_allowed_prefixes') {
          setPrefixError(data as unknown as PrefixError)
          return
        }
      }
      const data = (err as { response?: { data?: { detail?: string; details?: { field: string; message: string }[] } } })?.response?.data
      const msg = data?.details?.map(d => `${d.field}: ${d.message}`).join('; ')
        ?? data?.detail
        ?? String(err)
      setFormError(msg)
    } finally { setSaving(false) }
  }

  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div className="bg-white rounded-xl shadow-2xl w-full max-w-md max-h-[90vh] overflow-y-auto">
          <div className="flex items-center justify-between px-6 py-4 border-b border-border sticky top-0 bg-white z-10">
            <h2 className="text-base font-semibold">New IP Pool</h2>
            <button onClick={onClose} className="btn-icon text-xl leading-none">×</button>
          </div>
          <div className="px-6 py-5 space-y-4">
            <div className="field">
              <label className="label">Pool Name *</label>
              <input className="input" placeholder="CGNAT Pool A" value={form.name} onChange={e => setF('name', e.target.value)} />
            </div>

            {/* Routing domain */}
            <div className="field">
              <label className="label">Routing Domain</label>
              <DomainComboBox
                domains={routingDomains}
                value={form.routing_domain}
                onChange={v => setF('routing_domain', v)}
                placeholder="default"
                allowFreeText
                error={!!(overlapError || prefixError)}
              />
              <p className="text-xs text-gray-400 mt-1">
                Pools in the same routing domain cannot have overlapping IP ranges.
              </p>
              {selectedDomain && selectedDomain.allowed_prefixes.length > 0 && (
                <p className="text-xs text-blue-600 mt-0.5">
                  Allowed subnets: {selectedDomain.allowed_prefixes.join(', ')}
                </p>
              )}
            </div>

            {/* Suggest CIDR helper — shown when selected domain has allowed_prefixes */}
            {canSuggest && (
              <div className="rounded-lg border border-border bg-page p-3 space-y-2">
                <p className="text-xs font-medium text-gray-600">Suggest a free subnet</p>
                <div className="flex gap-2 items-center">
                  <input
                    className="input text-sm font-mono flex-1 py-1.5"
                    type="number"
                    min={1}
                    placeholder="hosts needed (e.g. 254)"
                    value={suggestSize}
                    onChange={e => { setSuggestSize(e.target.value); setSuggestion(null); setSuggestError(null) }}
                    onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleSuggest() } }}
                  />
                  <button onClick={handleSuggest} disabled={!suggestSize || suggesting} className="btn-ghost text-xs py-1.5 px-3 whitespace-nowrap">
                    {suggesting ? '…' : 'Find'}
                  </button>
                </div>
                {suggestError && <p className="text-xs text-red-600">{suggestError}</p>}
                {suggestion && (
                  <p className="text-xs text-green-700">
                    ✓ <code className="font-mono font-semibold">{suggestion.suggested_cidr}</code> auto-filled below
                    ({suggestion.usable_hosts.toLocaleString()} usable hosts)
                  </p>
                )}
              </div>
            )}

            {/* Subnet */}
            <div className="field">
              <label className="label">Subnet (CIDR) *</label>
              <input
                className={`input font-mono ${(overlapError || prefixError || formError) ? 'border-red-400 focus:ring-red-300' : ''}`}
                placeholder="100.65.120.0/24"
                value={form.subnet}
                onChange={e => setF('subnet', e.target.value)}
              />
              {overlapError && (
                <div className="mt-2 flex gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2.5 text-xs text-amber-800">
                  <span className="shrink-0 text-amber-500 mt-0.5">⚠</span>
                  <span>
                    <span className="font-semibold">Overlapping IP range —</span>
                    {' '}{overlapError.detail}
                    <br />
                    Use a non-overlapping subnet, or select a different routing domain.
                  </span>
                </div>
              )}
              {prefixError && (
                <div className="mt-2 flex gap-2 rounded-lg border border-red-300 bg-red-50 px-3 py-2.5 text-xs text-red-800">
                  <span className="shrink-0 mt-0.5">✕</span>
                  <span>{prefixError.detail}</span>
                </div>
              )}
            </div>

            <div className="field">
              <label className="label">Account Name (optional)</label>
              <input className="input" placeholder="Melita" value={form.account_name} onChange={e => setF('account_name', e.target.value)} />
            </div>

            {formError && (
              <div className="flex gap-2 rounded-lg border border-red-300 bg-red-50 px-3 py-2.5 text-xs text-red-800">
                <span className="shrink-0 mt-0.5">✕</span>
                <span>{formError}</span>
              </div>
            )}

            <div className="flex gap-3 pt-2 border-t border-border">
              <button onClick={onClose} className="btn-ghost">Cancel</button>
              <button
                onClick={handleCreate}
                disabled={!form.name || !form.subnet || saving}
                className="btn-primary ml-auto"
              >
                {saving ? 'Creating…' : 'Create Pool'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

// ─── Router ───────────────────────────────────────────────────────────────────
export default function Pools() {
  return (
    <Routes>
      <Route index          element={<PoolList />} />
      <Route path=":pool_id" element={<PoolDetail />} />
    </Routes>
  )
}
