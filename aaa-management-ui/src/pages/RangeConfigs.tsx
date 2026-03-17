import { useEffect, useState } from 'react'
import { Routes, Route, useNavigate, useParams } from 'react-router-dom'
import { apiClient } from '../apiClient'
import StatusBadge from '../components/StatusBadge'
import { useToasts } from '../stores/toast'
import type { RangeConfig, ApnPool, Pool, IpResolution } from '../types'

const IP_RES_LABELS: Record<IpResolution, string> = {
  imsi:     'IMSI',
  imsi_apn: 'IMSI + APN',
  iccid:    'ICCID',
  iccid_apn:'ICCID + APN',
}

// ─── Range Config List ────────────────────────────────────────────────────────
function RangeConfigList() {
  const navigate     = useNavigate()
  const { show }     = useToasts()
  const [configs,    setConfigs]  = useState<RangeConfig[]>([])
  const [loading,    setLoading]  = useState(true)
  const [error,      setError]    = useState<string | null>(null)
  const [showNew,    setShowNew]  = useState(false)
  const [apnCounts,  setApnCounts] = useState<Record<number, number>>({})

  async function load() {
    setLoading(true)
    try {
      const res = await apiClient.get('/range-configs')
      const list: RangeConfig[] = res.data.items ?? res.data.configs ?? res.data ?? []
      setConfigs(list)

      // Fetch APN pool counts for configs that use APN resolution
      const apnRes = await Promise.allSettled(
        list
          .filter(c => c.ip_resolution === 'imsi_apn' || c.ip_resolution === 'iccid_apn')
          .map(async c => {
            const r = await apiClient.get(`/range-configs/${c.id}/apn-pools`)
            const pools: ApnPool[] = r.data.items ?? r.data.apn_pools ?? r.data ?? []
            return { id: c.id, count: pools.length }
          })
      )
      const counts: Record<number, number> = {}
      apnRes.forEach(r => { if (r.status === 'fulfilled') counts[r.value.id] = r.value.count })
      setApnCounts(counts)
    } catch (e) { setError(String(e)) } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  async function createConfig(form: NewConfigForm) {
    try {
      await apiClient.post('/range-configs', form)
      show('success', 'Range config created')
      setShowNew(false); load()
    } catch (e) { show('error', String(e)) }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs text-gray-400 uppercase tracking-widest font-medium">Configuration</p>
          <h1 className="page-title">IMSI Range Configs</h1>
        </div>
        <button onClick={() => setShowNew(true)} className="btn-primary">+ New Config</button>
      </div>

      {error && <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-lg">{error}</div>}
      {showNew && <NewConfigModal onClose={() => setShowNew(false)} onSave={createConfig} />}

      <div className="tbl-wrap">
        {loading ? (
          <div className="flex items-center justify-center h-40 text-gray-400 text-sm">Loading…</div>
        ) : configs.length === 0 ? (
          <div className="flex items-center justify-center h-40 text-gray-400 text-sm">No range configs configured.</div>
        ) : (
          <table className="tbl">
            <thead><tr>
              <th>ID</th><th>Account</th><th>IMSI Range</th><th>Pool</th>
              <th>IP Resolution</th><th className="text-center">APN Pools</th>
              <th>Status</th><th />
            </tr></thead>
            <tbody>
              {configs.map(c => (
                <tr key={c.id}
                  className="border-b border-border hover:bg-page transition-colors cursor-pointer"
                  onClick={() => navigate(String(c.id))}>
                  <td className="px-4 py-3 font-mono text-xs text-gray-500">#{c.id}</td>
                  <td className="px-4 py-3 text-sm">{c.account_name ?? <span className="text-gray-300">—</span>}</td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-700">
                    <span className="text-gray-400">{c.f_imsi}</span>
                    <span className="mx-1 text-gray-300">→</span>
                    <span className="text-gray-400">{c.t_imsi}</span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">{c.pool_name ?? c.pool_id ?? <span className="text-gray-300">—</span>}</td>
                  <td className="px-4 py-3">
                    <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full font-medium">
                      {IP_RES_LABELS[c.ip_resolution]}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-center text-sm tabular-nums text-gray-600">
                    {(c.ip_resolution === 'imsi_apn' || c.ip_resolution === 'iccid_apn')
                      ? (apnCounts[c.id] ?? '—')
                      : <span className="text-gray-300">N/A</span>}
                  </td>
                  <td className="px-4 py-3"><StatusBadge status={c.status} /></td>
                  <td className="px-4 py-3 text-right"><span className="text-xs text-primary">View →</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

// ─── Range Config Detail ──────────────────────────────────────────────────────
function RangeConfigDetail() {
  const { id }    = useParams<{ id: string }>()
  const navigate  = useNavigate()
  const { show }  = useToasts()
  const [config,   setConfig]  = useState<RangeConfig | null>(null)
  const [apnPools, setApnPools] = useState<ApnPool[]>([])
  const [loading,  setLoading] = useState(true)
  const [error,    setError]   = useState<string | null>(null)
  const [editing,  setEditing] = useState(false)
  const [editForm, setEditForm] = useState<Partial<RangeConfig>>({})
  const [newApn,   setNewApn]  = useState('')
  const [newPool,  setNewPool]  = useState('')
  const [pools,    setPools]   = useState<Pool[]>([])

  async function load() {
    if (!id) return; setLoading(true)
    try {
      const r = await apiClient.get(`/range-configs/${id}`)
      setConfig(r.data)
      if (r.data.ip_resolution === 'imsi_apn' || r.data.ip_resolution === 'iccid_apn') {
        const ar = await apiClient.get(`/range-configs/${id}/apn-pools`)
        setApnPools(ar.data.items ?? ar.data.apn_pools ?? ar.data ?? [])
      }
    } catch (e) { setError(String(e)) } finally { setLoading(false) }
  }

  async function loadPools() {
    try {
      const r = await apiClient.get('/pools')
      setPools(r.data.pools ?? r.data.items ?? [])
    } catch { /* ignore */ }
  }

  useEffect(() => { load(); loadPools() }, [id]) // eslint-disable-line

  async function saveEdit() {
    try {
      await apiClient.patch(`/range-configs/${id}`, editForm)
      show('success', 'Config updated'); setEditing(false); load()
    } catch (e) { show('error', String(e)) }
  }

  async function deleteConfig() {
    if (!confirm('Delete this range config?')) return
    try {
      await apiClient.delete(`/range-configs/${id}`)
      show('success', 'Config deleted'); navigate('/range-configs')
    } catch (e) { show('error', String(e)) }
  }

  async function addApnPool() {
    if (!newApn || !newPool) return
    try {
      await apiClient.post(`/range-configs/${id}/apn-pools`, { apn: newApn, pool_id: newPool })
      show('success', 'APN pool added'); setNewApn(''); setNewPool(''); load()
    } catch (e) { show('error', String(e)) }
  }

  async function removeApnPool(apn: string) {
    if (!confirm(`Remove APN override for "${apn}"?`)) return
    try {
      await apiClient.delete(`/range-configs/${id}/apn-pools/${encodeURIComponent(apn)}`)
      show('success', 'APN pool removed'); load()
    } catch (e) { show('error', String(e)) }
  }

  if (loading) return <div className="flex items-center justify-center h-60 text-gray-400 text-sm">Loading…</div>
  if (error)   return <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">{error}</div>
  if (!config) return null

  const usesApn = config.ip_resolution === 'imsi_apn' || config.ip_resolution === 'iccid_apn'

  return (
    <div className="space-y-4 max-w-3xl">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm">
        <button onClick={() => navigate('/range-configs')} className="text-primary hover:underline">IMSI Range Configs</button>
        <span className="text-gray-400">/</span>
        <span className="text-gray-600">#{config.id}</span>
      </div>

      {/* Main card */}
      <div className="card p-6 space-y-5">
        <div className="flex items-start justify-between">
          <div>
            {editing ? (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div className="field">
                    <label className="label">Account Name</label>
                    <input className="input text-sm" value={editForm.account_name ?? ''} onChange={e => setEditForm(f => ({ ...f, account_name: e.target.value }))} />
                  </div>
                  <div className="field">
                    <label className="label">Description</label>
                    <input className="input text-sm" value={editForm.description ?? ''} onChange={e => setEditForm(f => ({ ...f, description: e.target.value }))} />
                  </div>
                  <div className="field">
                    <label className="label">IP Resolution</label>
                    <select className="select text-sm" value={editForm.ip_resolution ?? config.ip_resolution}
                      onChange={e => setEditForm(f => ({ ...f, ip_resolution: e.target.value as IpResolution }))}>
                      {(Object.entries(IP_RES_LABELS) as [IpResolution, string][]).map(([v, l]) => (
                        <option key={v} value={v}>{l}</option>
                      ))}
                    </select>
                  </div>
                  <div className="field">
                    <label className="label">Pool</label>
                    <select className="select text-sm" value={editForm.pool_id ?? config.pool_id ?? ''}
                      onChange={e => setEditForm(f => ({ ...f, pool_id: e.target.value || null }))}>
                      <option value="">— none —</option>
                      {pools.map(p => <option key={p.pool_id} value={p.pool_id}>{p.name}</option>)}
                    </select>
                  </div>
                </div>
                <div className="flex gap-2">
                  <button onClick={saveEdit} className="btn-primary text-xs py-1.5 px-3">Save</button>
                  <button onClick={() => setEditing(false)} className="btn-ghost text-xs">Cancel</button>
                </div>
              </div>
            ) : (
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-lg font-semibold text-gray-900">Range Config #{config.id}</h2>
                  <button onClick={() => { setEditForm({ ...config }); setEditing(true) }}
                    className="text-xs text-gray-400 hover:text-gray-600">Edit</button>
                </div>
                {config.description && <p className="text-sm text-gray-500 mt-0.5">{config.description}</p>}
              </div>
            )}
          </div>
          {!editing && (
            <div className="flex gap-2">
              <StatusBadge status={config.status} />
              <button onClick={deleteConfig} className="btn-danger text-xs py-1 px-3">Delete</button>
            </div>
          )}
        </div>

        {/* Info grid */}
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
          {[
            { l: 'Account',    v: config.account_name ?? '—' },
            { l: 'From IMSI',  v: config.f_imsi },
            { l: 'To IMSI',    v: config.t_imsi },
            { l: 'Pool',       v: config.pool_name ?? config.pool_id ?? '—' },
            { l: 'IP Resolution', v: IP_RES_LABELS[config.ip_resolution] },
          ].map(f => (
            <div key={f.l}>
              <p className="text-xs text-gray-400 uppercase tracking-wide font-medium mb-0.5">{f.l}</p>
              <p className="font-mono text-sm text-gray-800">{f.v}</p>
            </div>
          ))}
        </div>
      </div>

      {/* APN Pool Manager */}
      {usesApn && (
        <div className="card p-6 space-y-4">
          <h3 className="text-sm font-semibold text-gray-900">APN Pool Overrides</h3>
          <p className="text-xs text-gray-400">
            Per-APN pool routing — when a device connects on a specific APN, traffic is routed through its designated pool.
          </p>

          {apnPools.length === 0 ? (
            <p className="text-sm text-gray-400 italic">No APN pool overrides configured.</p>
          ) : (
            <table className="tbl">
              <thead><tr>
                <th>APN</th><th>Pool</th><th />
              </tr></thead>
              <tbody>
                {apnPools.map(ap => (
                  <tr key={ap.id} className="border-b border-border">
                    <td className="px-4 py-2.5 font-mono text-xs text-gray-700">{ap.apn}</td>
                    <td className="px-4 py-2.5 text-sm text-gray-600">{ap.pool_name ?? ap.pool_id}</td>
                    <td className="px-4 py-2.5 text-right">
                      <button
                        onClick={() => removeApnPool(ap.apn)}
                        className="text-xs text-red-500 hover:text-red-700 font-medium">
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {/* Add APN override */}
          <div className="pt-3 border-t border-border">
            <p className="text-xs font-medium text-gray-700 mb-2">Add APN Override</p>
            <div className="flex gap-2 items-end">
              <div className="field flex-1 mb-0">
                <label className="label">APN</label>
                <input className="input text-sm" placeholder="internet.operator.com"
                  value={newApn} onChange={e => setNewApn(e.target.value)} />
              </div>
              <div className="field flex-1 mb-0">
                <label className="label">Pool</label>
                <select className="select text-sm" value={newPool} onChange={e => setNewPool(e.target.value)}>
                  <option value="">— select pool —</option>
                  {pools.map(p => <option key={p.pool_id} value={p.pool_id}>{p.name}</option>)}
                </select>
              </div>
              <button
                onClick={addApnPool}
                disabled={!newApn || !newPool}
                className="btn-primary text-sm py-2 px-4 shrink-0">
                Add
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── New Config Modal ─────────────────────────────────────────────────────────
type NewConfigForm = {
  account_name:  string
  f_imsi:        string
  t_imsi:        string
  pool_id:       string
  ip_resolution: IpResolution
  description:   string
}

function NewConfigModal({
  onClose, onSave,
}: { onClose: () => void; onSave: (f: NewConfigForm) => void }) {
  const [form, setForm] = useState<NewConfigForm>({
    account_name: '', f_imsi: '', t_imsi: '', pool_id: '', ip_resolution: 'imsi', description: '',
  })
  const [pools, setPools] = useState<Pool[]>([])
  const setF = <K extends keyof NewConfigForm>(k: K, v: NewConfigForm[K]) =>
    setForm(f => ({ ...f, [k]: v }))

  useEffect(() => {
    apiClient.get('/pools').then(r => setPools(r.data.pools ?? r.data.items ?? [])).catch(() => {})
  }, [])

  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg">
          <div className="flex items-center justify-between px-6 py-4 border-b border-border">
            <h2 className="text-base font-semibold">New IMSI Range Config</h2>
            <button onClick={onClose} className="btn-icon text-xl leading-none">×</button>
          </div>
          <div className="px-6 py-5 space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="field">
                <label className="label">From IMSI *</label>
                <input className="input font-mono text-sm" placeholder="310260000000000"
                  value={form.f_imsi} onChange={e => setF('f_imsi', e.target.value)} />
              </div>
              <div className="field">
                <label className="label">To IMSI *</label>
                <input className="input font-mono text-sm" placeholder="310260000099999"
                  value={form.t_imsi} onChange={e => setF('t_imsi', e.target.value)} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="field">
                <label className="label">Account Name</label>
                <input className="input text-sm" placeholder="Operator A"
                  value={form.account_name} onChange={e => setF('account_name', e.target.value)} />
              </div>
              <div className="field">
                <label className="label">IP Resolution *</label>
                <select className="select text-sm" value={form.ip_resolution}
                  onChange={e => setF('ip_resolution', e.target.value as IpResolution)}>
                  {(Object.entries(IP_RES_LABELS) as [IpResolution, string][]).map(([v, l]) => (
                    <option key={v} value={v}>{l}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="field">
              <label className="label">Default Pool</label>
              <select className="select text-sm" value={form.pool_id}
                onChange={e => setF('pool_id', e.target.value)}>
                <option value="">— none —</option>
                {pools.map(p => <option key={p.pool_id} value={p.pool_id}>{p.name}</option>)}
              </select>
            </div>
            <div className="field">
              <label className="label">Description</label>
              <input className="input text-sm" placeholder="Optional note"
                value={form.description} onChange={e => setF('description', e.target.value)} />
            </div>
            <div className="flex gap-3 pt-2 border-t border-border">
              <button onClick={onClose} className="btn-ghost">Cancel</button>
              <button
                onClick={() => onSave(form)}
                disabled={!form.f_imsi || !form.t_imsi}
                className="btn-primary ml-auto">
                Create Config
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

// ─── Router ───────────────────────────────────────────────────────────────────
export default function RangeConfigs() {
  return (
    <Routes>
      <Route index         element={<RangeConfigList />} />
      <Route path=":id"    element={<RangeConfigDetail />} />
    </Routes>
  )
}
