import { useEffect, useState } from 'react'
import { Routes, Route, useNavigate, useParams } from 'react-router-dom'
import { apiClient } from '../apiClient'
import StatusBadge from '../components/StatusBadge'
import { useToasts } from '../stores/toast'
import type { Pool, PoolStats } from '../types'

function poolBarColor(pct: number) {
  if (pct > 90) return '#E53E3E'
  if (pct > 75) return '#E07B39'
  return '#F5A623'
}

// ─── Pool List ────────────────────────────────────────────────────────────────
function PoolList() {
  const navigate  = useNavigate()
  const [pools,              setPools]             = useState<(Pool & PoolStats)[]>([])
  const [loading,            setLoading]           = useState(true)
  const [error,              setError]             = useState<string | null>(null)
  const [showNew,            setShowNew]           = useState(false)
  const [routingDomains,     setRoutingDomains]    = useState<string[]>([])
  const [domainFilter,       setDomainFilter]      = useState('')

  async function load() {
    setLoading(true)
    try {
      const params: Record<string, string> = {}
      if (domainFilter) params.routing_domain = domainFilter
      const res = await apiClient.get('/pools', { params })
      const list: Pool[] = res.data.pools ?? res.data.items ?? []
      // Fetch stats for each pool
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
      const res = await apiClient.get('/routing-domains')
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
        <select
          className="input text-sm py-1.5 w-52"
          value={domainFilter}
          onChange={e => setDomainFilter(e.target.value)}
        >
          <option value="">All domains</option>
          {routingDomains.map(d => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>
        {domainFilter && (
          <button onClick={() => setDomainFilter('')} className="text-xs text-gray-400 hover:text-gray-600">
            Clear
          </button>
        )}
      </div>

      {error && <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-lg">{error}</div>}

      {showNew && (
        <NewPoolModal
          routingDomains={routingDomains}
          onClose={() => setShowNew(false)}
          onSuccess={() => { setShowNew(false); load(); loadDomains() }}
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
          {/* Routing domain — full row, shown as a badge since it's immutable */}
          <div>
            <p className="text-xs text-gray-400 uppercase tracking-wide font-medium mb-1">Routing Domain</p>
            <span className="inline-flex items-center rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700 ring-1 ring-blue-200">
              {pool.routing_domain ?? 'default'}
            </span>
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

// ─── Overlap error shape returned by the API ──────────────────────────────────
interface OverlapError {
  error: 'pool_overlap'
  detail: string
  conflicting_pool_id: string
}

// ─── New Pool Modal ───────────────────────────────────────────────────────────
function NewPoolModal({
  routingDomains,
  onClose,
  onSuccess,
}: {
  routingDomains: string[]
  onClose: () => void
  onSuccess: () => void
}) {
  const [form, setForm] = useState({
    name: '', subnet: '', account_name: '', routing_domain: 'default',
  })
  const [saving,        setSaving]        = useState(false)
  const [overlapError,  setOverlapError]  = useState<OverlapError | null>(null)

  const setF = (k: string, v: string) => {
    setForm(f => ({ ...f, [k]: v }))
    // Clear overlap error when subnet or routing_domain changes
    if (k === 'subnet' || k === 'routing_domain') setOverlapError(null)
  }

  async function handleCreate() {
    setSaving(true)
    setOverlapError(null)
    try {
      await apiClient.post('/pools', {
        name:           form.name,
        subnet:         form.subnet,
        account_name:   form.account_name || undefined,
        routing_domain: form.routing_domain || 'default',
      })
      onSuccess()
    } catch (err: unknown) {
      const resp = (err as { response?: { status: number; data: unknown } })?.response
      if (resp?.status === 409) {
        const data = resp.data as { detail?: OverlapError }
        const detail = data?.detail ?? (data as unknown as OverlapError)
        if (detail && (detail as OverlapError).error === 'pool_overlap') {
          setOverlapError(detail as OverlapError)
          return
        }
      }
      // Generic error fallback
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        ?? String(err)
      alert(`Failed to create pool: ${msg}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div className="bg-white rounded-xl shadow-2xl w-full max-w-md">
          <div className="flex items-center justify-between px-6 py-4 border-b border-border">
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
              <input
                className={`input font-mono ${overlapError ? 'border-red-400 focus:ring-red-300' : ''}`}
                placeholder="default"
                list="routing-domain-suggestions"
                value={form.routing_domain}
                onChange={e => setF('routing_domain', e.target.value)}
              />
              <datalist id="routing-domain-suggestions">
                {routingDomains.map(d => <option key={d} value={d} />)}
              </datalist>
              <p className="text-xs text-gray-400 mt-1">
                Pools in the same routing domain cannot have overlapping IP ranges.
              </p>
            </div>

            {/* Subnet — overlap error shown inline here */}
            <div className="field">
              <label className="label">Subnet (CIDR) *</label>
              <input
                className={`input font-mono ${overlapError ? 'border-red-400 focus:ring-red-300' : ''}`}
                placeholder="100.65.120.0/24"
                value={form.subnet}
                onChange={e => setF('subnet', e.target.value)}
              />
              {overlapError && (
                <div className="mt-2 flex gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2.5 text-xs text-amber-800">
                  <span className="shrink-0 text-amber-500 mt-0.5">⚠</span>
                  <span>
                    {overlapError.detail}
                    <br />
                    Use a different subnet, or assign this pool to a different routing domain.
                  </span>
                </div>
              )}
            </div>

            <div className="field">
              <label className="label">Account Name (optional)</label>
              <input className="input" placeholder="Melita" value={form.account_name} onChange={e => setF('account_name', e.target.value)} />
            </div>

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
