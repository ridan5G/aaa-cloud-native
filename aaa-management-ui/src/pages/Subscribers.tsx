import { useEffect, useState } from 'react'
import { Routes, Route, Link, useNavigate, useParams } from 'react-router-dom'
import { apiClient } from '../apiClient'
import StatusBadge from '../components/StatusBadge'
import { useToasts } from '../stores/toast'
import { ProfileDiagram } from '../components/SimProfileDiagram'
import type { Profile, Imsi, IccidIp, Pool, IpResolution } from '../types'

const IP_RESOLUTIONS: IpResolution[] = ['imsi', 'imsi_apn', 'iccid', 'iccid_apn']
const PER_PAGE = 50

function fmtDate(s: string) {
  return new Date(s).toLocaleDateString(undefined, { dateStyle: 'medium' })
}

// ─── List ─────────────────────────────────────────────────────────────────────
function DeviceList() {
  const navigate  = useNavigate()
  const { show }  = useToasts()
  const [items,   setItems]   = useState<Profile[]>([])
  const [total,   setTotal]   = useState(0)
  const [page,    setPage]    = useState(1)
  const [status,       setStatus]       = useState('')
  const [accountFilter, setAccountFilter] = useState('')
  const [imsiPrefix,    setImsiPrefix]    = useState('')
  const [iccidPrefix,   setIccidPrefix]   = useState('')
  const [ipResFilter,   setIpResFilter]   = useState('')
  const [ipFilter,      setIpFilter]      = useState('')
  const [poolFilter,    setPoolFilter]    = useState('')
  const [accounts,  setAccounts]  = useState<string[]>([])
  const [pools,     setPools]     = useState<Pool[]>([])
  const [loading,   setLoading]   = useState(false)
  const [exporting, setExporting] = useState(false)
  const [error,     setError]     = useState<string | null>(null)

  useEffect(() => {
    apiClient.get('/profiles/accounts').then(r => setAccounts(r.data ?? [])).catch(() => {})
  }, [])
  useEffect(() => {
    apiClient.get('/pools').then(r => setPools(r.data.pools ?? r.data.items ?? [])).catch(() => {})
  }, [])

  async function load(
    st       = status,       pg       = page,
    acc      = accountFilter, ipRes   = ipResFilter,
    imsiPfx  = imsiPrefix,   iccidPfx = iccidPrefix,
    ipAddr   = ipFilter,     poolId   = poolFilter,
  ) {
    setLoading(true); setError(null)
    try {
      const params: Record<string, string | number> = { page: pg, limit: PER_PAGE }
      if (st)              params.status        = st
      if (acc)             params.account_name  = acc
      if (ipRes)           params.ip_resolution = ipRes
      if (imsiPfx.trim())  params.imsi_prefix   = imsiPfx.trim()
      if (iccidPfx.trim()) params.iccid_prefix  = iccidPfx.trim()
      if (ipAddr.trim())   params.ip            = ipAddr.trim()
      if (poolId)          params.pool_id       = poolId
      const res = await apiClient.get('/profiles', { params })
      setItems(res.data.items ?? res.data.profiles ?? [])
      setTotal(res.data.total ?? 0)
    } catch (e) { setError(String(e)) } finally { setLoading(false) }
  }

  useEffect(() => { load() }, []) // eslint-disable-line

  function handleSearch(e: React.FormEvent) {
    e.preventDefault(); setPage(1)
    load(status, 1, accountFilter, ipResFilter, imsiPrefix, iccidPrefix, ipFilter, poolFilter)
  }
  function handleSelectFilter(field: 'status' | 'account' | 'ipRes' | 'pool', v: string) {
    if (field === 'status')  { setStatus(v);        setPage(1); load(v,      1, accountFilter, ipResFilter, imsiPrefix, iccidPrefix, ipFilter, poolFilter) }
    if (field === 'account') { setAccountFilter(v); setPage(1); load(status, 1, v,             ipResFilter, imsiPrefix, iccidPrefix, ipFilter, poolFilter) }
    if (field === 'ipRes')   { setIpResFilter(v);   setPage(1); load(status, 1, accountFilter, v,           imsiPrefix, iccidPrefix, ipFilter, poolFilter) }
    if (field === 'pool')    { setPoolFilter(v);    setPage(1); load(status, 1, accountFilter, ipResFilter, imsiPrefix, iccidPrefix, ipFilter, v) }
  }
  function handleReset() {
    setStatus(''); setAccountFilter(''); setImsiPrefix(''); setIccidPrefix(''); setIpResFilter(''); setIpFilter(''); setPoolFilter('')
    setPage(1); load('', 1, '', '', '', '', '', '')
  }
  function goPage(p: number) { setPage(p); load(status, p, accountFilter, ipResFilter, imsiPrefix, iccidPrefix, ipFilter, poolFilter) }
  const totalPages = Math.ceil(total / PER_PAGE)

  async function handleExport() {
    setExporting(true)
    try {
      const params: Record<string, string> = {}
      if (status)             params.status        = status
      if (accountFilter)      params.account_name  = accountFilter
      if (ipResFilter)        params.ip_resolution = ipResFilter
      if (imsiPrefix.trim())  params.imsi_prefix   = imsiPrefix.trim()
      if (iccidPrefix.trim()) params.iccid_prefix  = iccidPrefix.trim()
      if (ipFilter.trim())    params.ip            = ipFilter.trim()
      if (poolFilter)         params.pool_id       = poolFilter

      const res = await apiClient.get('/profiles/export', { params })
      const rows: Record<string, string | null>[] = res.data

      const headers = ['sim_id', 'iccid', 'account_name', 'status', 'ip_resolution', 'imsi', 'apn', 'static_ip', 'pool_id']
      const cell = (v: string | null | undefined) => {
        const s = v ?? ''
        return s.includes(',') || s.includes('"') || s.includes('\n') ? `"${s.replace(/"/g, '""')}"` : s
      }
      const lines = [
        headers.join(','),
        ...rows.map(r => [
          r.sim_id, r.iccid, r.account_name, r.status, r.ip_resolution,
          r.imsi, r.apn, r.static_ip, r.pool_id,
        ].map(cell).join(',')),
      ]
      const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/csv' }))
      const fname = `sims-export-${new Date().toISOString().slice(0, 10)}.csv`
      Object.assign(document.createElement('a'), { href: url, download: fname }).click()
      URL.revokeObjectURL(url)
      show('success', `Exported ${rows.length} rows`)
    } catch (e) { show('error', String(e)) } finally { setExporting(false) }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs text-gray-400 uppercase tracking-widest font-medium">Provisioning</p>
          <h1 className="page-title">SIMs</h1>
        </div>
        <div className="flex gap-2">
          <button onClick={handleExport} disabled={exporting} className="btn-outline">
            {exporting ? 'Exporting…' : '↓ Export CSV'}
          </button>
          <Link to="bulk" className="btn-outline">↑ Bulk Import</Link>
          <Link to="new"  className="btn-primary">+ New Profile</Link>
        </div>
      </div>

      {/* Quick-action: pick a profile type before creating */}
      <Link
        to="/sim-profile-types"
        className="flex items-center gap-3 px-4 py-3 bg-primary/5 border border-primary/20 rounded-lg hover:bg-primary/10 transition-colors group"
      >
        <div className="w-7 h-7 rounded-full bg-primary/10 text-primary flex items-center justify-center shrink-0">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" className="w-3.5 h-3.5">
            <path d="M8 3v10M3 8h10" strokeLinecap="round" />
          </svg>
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-gray-800">Create a new SIM</p>
          <p className="text-xs text-gray-500 mt-0.5">Choose a profile type — IMSI, IMSI+APN, ICCID, or ICCID+APN</p>
        </div>
        <span className="text-primary text-sm font-medium shrink-0 group-hover:translate-x-0.5 transition-transform">
          Pick type →
        </span>
      </Link>

      <form onSubmit={handleSearch} className="flex gap-3 flex-wrap items-end">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-gray-500 font-medium">Account</label>
          <select className="select w-44" value={accountFilter}
            onChange={e => handleSelectFilter('account', e.target.value)}>
            <option value="">All accounts</option>
            {accounts.map(a => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-gray-500 font-medium">Profile Type</label>
          <select className="select w-40" value={ipResFilter}
            onChange={e => handleSelectFilter('ipRes', e.target.value)}>
            <option value="">All types</option>
            {IP_RESOLUTIONS.map(r => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-gray-500 font-medium">Status</label>
          <select className="select w-36" value={status}
            onChange={e => handleSelectFilter('status', e.target.value)}>
            <option value="">All statuses</option>
            <option value="active">Active</option>
            <option value="suspended">Suspended</option>
            <option value="terminated">Terminated</option>
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-gray-500 font-medium">Pool</label>
          <select className="select w-44" value={poolFilter}
            onChange={e => handleSelectFilter('pool', e.target.value)}>
            <option value="">All pools</option>
            {pools.map(p => <option key={p.pool_id} value={p.pool_id}>{p.name}</option>)}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-gray-500 font-medium">IMSI Prefix</label>
          <input className="input w-36 font-mono text-xs" placeholder="2787730…"
            value={imsiPrefix} onChange={e => setImsiPrefix(e.target.value)} />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-gray-500 font-medium">ICCID Prefix</label>
          <input className="input w-40 font-mono text-xs" placeholder="89445010…"
            value={iccidPrefix} onChange={e => setIccidPrefix(e.target.value)} />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-gray-400 font-medium">IP Address</label>
          <input className="input w-36 font-mono text-xs" placeholder="100.65.0.1"
            value={ipFilter} onChange={e => setIpFilter(e.target.value)} />
        </div>
        <button type="submit" className="btn-primary">Search</button>
        <button type="button" onClick={handleReset} className="btn-ghost">Reset</button>
      </form>

      {error && <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-lg">{error}</div>}

      <div className="tbl-wrap">
        {loading ? (
          <div className="flex items-center justify-center h-40 text-gray-400 text-sm">Loading…</div>
        ) : items.length === 0 ? (
          <div className="flex items-center justify-center h-40 text-gray-400 text-sm">No profiles found.</div>
        ) : (
          <>
            <table className="tbl">
              <thead><tr>
                <th>SIM ID</th><th>ICCID</th><th>Account</th>
                <th>Status</th><th>IP Resolution</th><th>IMSIs</th><th>Created</th><th />
              </tr></thead>
              <tbody>
                {items.map(p => (
                  <tr key={p.sim_id}
                    className={`border-b transition-colors cursor-pointer ${
                      p.status === 'terminated'
                        ? 'bg-red-50 border-l-2 border-l-red-400 hover:bg-red-100'
                        : 'border-border hover:bg-page'
                    }`}
                    onClick={() => navigate(p.sim_id)}>
                    <td className="px-4 py-3 font-mono text-xs text-gray-500">{p.sim_id.slice(0, 8)}…</td>
                    <td className="px-4 py-3 text-sm font-mono text-xs">
                      {p.iccid ? p.iccid.slice(0, 12) + '…' : <span className="text-gray-400">—</span>}
                    </td>
                    <td className="px-4 py-3 text-sm">{p.account_name ?? <span className="text-gray-400">—</span>}</td>
                    <td className="px-4 py-3"><StatusBadge status={p.status} /></td>
                    <td className="px-4 py-3">
                      <span className="px-2 py-0.5 bg-gray-100 text-gray-600 text-xs rounded font-mono">{p.ip_resolution}</span>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500 tabular-nums">{p.imsis?.length ?? '—'}</td>
                    <td className="px-4 py-3 text-sm text-gray-500 whitespace-nowrap">{fmtDate(p.created_at)}</td>
                    <td className="px-4 py-3 text-right"><span className="text-xs text-primary">View →</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="px-4 py-3 border-t border-border flex items-center justify-between text-xs text-gray-500">
              <span>{((page-1)*PER_PAGE+1).toLocaleString()}–{Math.min(page*PER_PAGE,total).toLocaleString()} of {total.toLocaleString()}</span>
              <div className="flex gap-1">
                <button className="px-2 py-1 border border-border rounded hover:bg-page disabled:opacity-40"
                  disabled={page<=1} onClick={() => goPage(page-1)}>← Prev</button>
                <button className="px-2 py-1 border border-border rounded hover:bg-page disabled:opacity-40"
                  disabled={page>=totalPages} onClick={() => goPage(page+1)}>Next →</button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ─── Profile type banner ──────────────────────────────────────────────────────
const IP_RES_META: Record<IpResolution, { label: string; color: string; desc: string }> = {
  imsi:     { label: 'IMSI',        color: 'bg-blue-50 text-blue-700 border-blue-200',   desc: 'Per-IMSI, APN-agnostic — each IMSI gets its own IP' },
  imsi_apn: { label: 'IMSI + APN',  color: 'bg-amber-50 text-amber-700 border-amber-300', desc: 'Per-IMSI, per-APN — each IMSI×APN pair gets a dedicated IP' },
  iccid:    { label: 'ICCID',       color: 'bg-purple-50 text-purple-700 border-purple-300', desc: 'Card-level — all IMSIs on this SIM share one IP' },
  iccid_apn:{ label: 'ICCID + APN', color: 'bg-green-50 text-green-700 border-green-300',  desc: 'Card-level per-APN — all IMSIs share per-APN IPs' },
}

// Sub-component: renders iccid_ips card for iccid/iccid_apn modes
function CardIpSection({ iccidIps }: { iccidIps: IccidIp[] }) {
  if (!iccidIps.length) return (
    <div className="text-xs text-gray-400 italic py-2">No card-level IPs allocated yet — assigned on first connection.</div>
  )
  return (
    <table className="tbl">
      <thead><tr>
        <th>APN</th><th>Static IP</th><th>Pool</th>
      </tr></thead>
      <tbody>
        {iccidIps.map((ip, i) => (
          <tr key={i} className="border-b border-border">
            <td className="px-4 py-2.5 font-mono text-xs text-gray-600">{ip.apn ?? <span className="text-gray-300 not-italic">— any APN —</span>}</td>
            <td className="px-4 py-2.5 font-mono text-xs text-gray-800">{ip.static_ip ?? <span className="text-gray-400 not-italic">Auto</span>}</td>
            <td className="px-4 py-2.5 text-xs text-gray-500">{ip.pool_name ?? ip.pool_id ?? '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// Sub-component: renders per-IMSI APN IPs (for imsi_apn mode, expanded view)
function ImsiApnIpsList({ apnIps }: { apnIps: { apn: string | null; static_ip: string | null; pool_name?: string | null; pool_id?: string | null }[] }) {
  if (!apnIps.length) return <span className="text-gray-400 text-xs italic">No IPs</span>
  return (
    <div className="space-y-0.5">
      {apnIps.map((ip, i) => (
        <div key={i} className="flex items-center gap-1.5 text-xs">
          <span className="text-amber-600 font-mono truncate max-w-[100px]">{ip.apn ?? 'any'}</span>
          <span className="text-gray-300">→</span>
          <span className="font-mono text-gray-700">{ip.static_ip ?? 'Auto'}</span>
        </div>
      ))}
    </div>
  )
}

// ─── Profile Detail ───────────────────────────────────────────────────────────
function ProfileDetail() {
  const { sim_id } = useParams<{ sim_id: string }>()
  const navigate = useNavigate()
  const { show } = useToasts()
  const [profile, setProfile] = useState<Profile | null>(null)
  const [imsis,   setImsis]   = useState<Imsi[]>([])
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [newImsi, setNewImsi] = useState({ imsi: '', priority: '1', static_ip: '', pool_id: '' })
  const [saving,  setSaving]  = useState(false)
  const [connecting, setConnecting] = useState(false)

  async function load() {
    if (!sim_id) return
    setLoading(true)
    try {
      const [pr, ir] = await Promise.all([
        apiClient.get(`/profiles/${sim_id}`),
        apiClient.get(`/profiles/${sim_id}/imsis`).catch(() => ({ data: [] })),
      ])
      setProfile(pr.data)
      const d = ir.data
      const rawImsis = Array.isArray(d) ? d : d.items ?? d.imsis ?? []
      setImsis(rawImsis.length > 0 ? rawImsis : (pr.data.imsis ?? []))
    } catch (e) { setError(String(e)) } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [sim_id]) // eslint-disable-line

  async function patchProfile(body: Record<string, unknown>) {
    try { await apiClient.patch(`/profiles/${sim_id}`, body); show('success', 'Updated'); load() }
    catch (e) { show('error', String(e)) }
  }

  async function patchImsi(imsi: string, body: Record<string, unknown>) {
    try { await apiClient.patch(`/profiles/${sim_id}/imsis/${imsi}`, body); show('success', 'Updated'); load() }
    catch (e) { show('error', String(e)) }
  }

  async function deleteImsi(imsi: string) {
    if (!confirm(`Remove IMSI ${imsi}?`)) return
    try { await apiClient.delete(`/profiles/${sim_id}/imsis/${imsi}`); show('success', 'IMSI removed'); load() }
    catch (e) { show('error', String(e)) }
  }

  async function releaseIps() {
    if (!confirm(
      'Release all pool-managed IPs for this SIM?\n\n' +
      'IPs will be returned to the pool and re-allocated on the next first-connection.'
    )) return
    try {
      const r = await apiClient.post(`/profiles/${sim_id}/release-ips`)
      const { released_count } = r.data
      show('success', released_count > 0
        ? `Released ${released_count} IP(s) back to pool`
        : 'No pool-managed IPs to release')
      load()
    } catch (e) { show('error', String(e)) }
  }

  async function simulateFirstConnect() {
    const imsi = imsis[0]?.imsi
    if (!imsi) { show('error', 'No IMSIs on this SIM'); return }
    // Use first known APN from existing IP mappings; fall back to dummy for APN-agnostic modes
    const apn = imsis[0]?.apn_ips?.[0]?.apn ?? profile?.iccid_ips?.[0]?.apn ?? 'internet'
    setConnecting(true)
    try {
      const r = await apiClient.post('/first-connection', { imsi, apn })
      const { static_ip } = r.data
      if (static_ip) {
        show('success', r.status === 201 ? `IP allocated: ${static_ip}` : `Already provisioned: ${static_ip}`)
      } else {
        show('info', 'SIM has no range config — IP cannot be auto-allocated')
      }
      load()
    } catch (e: any) {
      const msg = e?.response?.data?.detail?.error ?? e?.response?.data?.error ?? String(e)
      show('error', msg === 'not_found' ? 'IMSI not found in any range config' : msg)
    }
    finally { setConnecting(false) }
  }

  async function addImsi() {
    setSaving(true)
    try {
      const apn_ips = newImsi.static_ip || newImsi.pool_id
        ? [{ apn: null, static_ip: newImsi.static_ip || null, pool_id: newImsi.pool_id || null }] : []
      await apiClient.post(`/profiles/${sim_id}/imsis`, {
        imsi: newImsi.imsi, priority: parseInt(newImsi.priority, 10), apn_ips,
      })
      show('success', 'IMSI added'); setShowForm(false)
      setNewImsi({ imsi: '', priority: '1', static_ip: '', pool_id: '' }); load()
    } catch (e) { show('error', String(e)) } finally { setSaving(false) }
  }

  if (loading) return <div className="flex items-center justify-center h-60 text-gray-400 text-sm">Loading…</div>
  if (error)   return <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">{error}</div>
  if (!profile) return null

  const resMeta = IP_RES_META[profile.ip_resolution] ?? { label: profile.ip_resolution, color: 'bg-gray-100 text-gray-600 border-gray-200', desc: '' }
  const isIccidMode = profile.ip_resolution === 'iccid' || profile.ip_resolution === 'iccid_apn'
  const isApnMode   = profile.ip_resolution === 'imsi_apn' || profile.ip_resolution === 'iccid_apn'
  const iccidIps: IccidIp[] = profile.iccid_ips ?? []

  return (
    <div className="space-y-4 max-w-4xl">
      <div className="flex items-center gap-2 text-sm">
        <button onClick={() => navigate('/devices')} className="text-primary hover:underline">SIMs</button>
        <span className="text-gray-400">/</span>
        <span className="font-mono text-xs text-gray-600">{profile.sim_id.slice(0, 16)}…</span>
      </div>

      {profile.status === 'terminated' && (
        <div className="flex items-center gap-3 px-4 py-3 bg-red-50 border border-red-300 rounded-lg text-red-700">
          <svg viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5 shrink-0">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z" clipRule="evenodd" />
          </svg>
          <div>
            <p className="text-sm font-semibold">This SIM has been terminated</p>
            <p className="text-xs mt-0.5 opacity-80">Profile is read-only. No further actions can be taken.</p>
          </div>
        </div>
      )}

      {/* Profile card */}
      <div className="card p-6 space-y-4">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs text-gray-400 uppercase tracking-wide font-medium">SIM Profile</p>
            <div className="flex items-center gap-2 mt-1">
              <span className="font-mono text-sm text-gray-700">{profile.sim_id}</span>
              <button className="text-xs text-gray-400 hover:text-gray-600 border border-gray-200 rounded px-1.5 py-0.5"
                onClick={() => { navigator.clipboard.writeText(profile.sim_id); show('info', 'Copied!') }}>
                Copy
              </button>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-wrap justify-end">
            {profile.status === 'active' && (
              <button onClick={() => patchProfile({ status: 'suspended' })} className="btn-ghost text-xs text-amber-600 border border-amber-200">Suspend</button>
            )}
            {profile.status === 'suspended' && (
              <button onClick={() => patchProfile({ status: 'active' })} className="btn-ghost text-xs text-green-600 border border-green-200">Reactivate</button>
            )}
            {profile.status === 'active' && (
              <button onClick={simulateFirstConnect} disabled={connecting}
                className="btn-ghost text-xs text-purple-600 border border-purple-200">
                {connecting ? 'Connecting…' : 'Simulate 1st Connect'}
              </button>
            )}
            {profile.status !== 'terminated' && (
              <button onClick={releaseIps} className="btn-ghost text-xs text-blue-600 border border-blue-200">Release IPs</button>
            )}
            {profile.status !== 'terminated' && (
              <button onClick={() => patchProfile({ status: 'terminated' })} className="btn-danger text-xs py-1 px-3">Terminate</button>
            )}
          </div>
        </div>

        {/* IP Resolution type badge + diagram */}
        <div className={`flex items-start gap-4 border rounded-lg px-4 py-3 ${resMeta.color}`}>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold uppercase tracking-wide">IP Resolution:</span>
              <code className="text-xs font-mono font-semibold">{profile.ip_resolution}</code>
            </div>
            <p className="text-xs mt-0.5 opacity-80">{resMeta.desc}</p>
            <Link to="/sim-profile-types" className="text-xs underline opacity-60 hover:opacity-100 mt-2 inline-block">Learn more</Link>
          </div>
          <div className="shrink-0 bg-white/70 rounded-lg px-3 py-2">
            <ProfileDiagram
              resolution={profile.ip_resolution}
              data={{ iccid: profile.iccid, imsis, iccidIps }}
            />
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          {[
            { l: 'ICCID',   v: profile.iccid ?? 'Not set',  mono: true },
            { l: 'Account', v: profile.account_name ?? '—', mono: false },
            { l: 'Created', v: fmtDate(profile.created_at),  mono: false },
            { l: 'Updated', v: fmtDate(profile.updated_at),  mono: false },
          ].map(f => (
            <div key={f.l}>
              <p className="text-xs text-gray-400 uppercase tracking-wide font-medium mb-0.5">{f.l}</p>
              <p className={`text-sm text-gray-800 ${f.mono ? 'font-mono' : ''}`}>{f.v}</p>
            </div>
          ))}
          <div>
            <p className="text-xs text-gray-400 uppercase tracking-wide font-medium mb-0.5">Status</p>
            <StatusBadge status={profile.status} />
          </div>
        </div>

        {profile.metadata && (profile.metadata.imei || profile.metadata.tags?.length) && (
          <div className="pt-3 border-t border-border grid grid-cols-2 gap-4">
            {profile.metadata.imei && (
              <div>
                <p className="text-xs text-gray-400 uppercase tracking-wide font-medium mb-0.5">IMEI</p>
                <p className="text-sm font-mono text-gray-700">{profile.metadata.imei}</p>
              </div>
            )}
            {profile.metadata.tags?.length && (
              <div>
                <p className="text-xs text-gray-400 uppercase tracking-wide font-medium mb-1">Tags</p>
                <div className="flex flex-wrap gap-1">
                  {profile.metadata.tags.map(t => (
                    <span key={t} className="px-2 py-0.5 bg-primary-light text-primary text-xs rounded-full">{t}</span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Card-level IPs (iccid / iccid_apn modes) */}
      {isIccidMode && (
        <div className="card overflow-hidden">
          <div className="px-5 py-4 border-b border-border">
            <h2 className="text-sm font-semibold">Card-Level IPs</h2>
            <p className="text-xs text-gray-400 mt-0.5">
              IPs assigned at the ICCID (card) level — shared across all IMSIs on this SIM
            </p>
          </div>
          <div className="p-5">
            <CardIpSection iccidIps={iccidIps} />
          </div>
        </div>
      )}

      {/* IMSI Manager */}
      <div className="card overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <h2 className="text-sm font-semibold">
            IMSIs ({imsis.length})
            {isIccidMode && <span className="ml-1.5 text-xs font-normal text-gray-400">— IPs are at card level above</span>}
          </h2>
          {profile.status !== 'terminated' && (
            <button onClick={() => setShowForm(v => !v)} className="btn-outline text-xs py-1.5 px-3">
              {showForm ? 'Cancel' : '+ Add IMSI'}
            </button>
          )}
        </div>

        {showForm && (
          <div className="px-5 py-4 bg-primary-light border-b border-border">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div className="field">
                <label className="label">IMSI (15 digits) *</label>
                <input className="input font-mono text-xs" placeholder="278773000002005"
                  value={newImsi.imsi} onChange={e => setNewImsi(p => ({ ...p, imsi: e.target.value }))} />
              </div>
              <div className="field">
                <label className="label">Priority</label>
                <input className="input" type="number" min="1"
                  value={newImsi.priority} onChange={e => setNewImsi(p => ({ ...p, priority: e.target.value }))} />
              </div>
              {!isIccidMode && (
                <>
                  <div className="field">
                    <label className="label">Static IP</label>
                    <input className="input font-mono text-xs" placeholder="100.65.0.1"
                      value={newImsi.static_ip} onChange={e => setNewImsi(p => ({ ...p, static_ip: e.target.value }))} />
                  </div>
                  <div className="field">
                    <label className="label">Pool ID</label>
                    <input className="input font-mono text-xs" placeholder="pool-uuid"
                      value={newImsi.pool_id} onChange={e => setNewImsi(p => ({ ...p, pool_id: e.target.value }))} />
                  </div>
                </>
              )}
            </div>
            <div className="flex gap-2 mt-3">
              <button onClick={addImsi} disabled={saving || !/^\d{15}$/.test(newImsi.imsi)} className="btn-primary text-xs py-1.5 px-4">
                {saving ? 'Saving…' : 'Add IMSI'}
              </button>
              <button onClick={() => setShowForm(false)} className="btn-ghost text-xs">Cancel</button>
            </div>
          </div>
        )}

        {imsis.length === 0 ? (
          <div className="flex items-center justify-center h-20 text-gray-400 text-sm">No IMSIs assigned.</div>
        ) : (
          <table className="tbl">
            <thead><tr>
              <th>IMSI</th>
              <th className="text-center w-16">Slot</th>
              <th>Status</th>
              {!isIccidMode && <th>{isApnMode ? 'APN → IP' : 'Static IP'}</th>}
              <th />
            </tr></thead>
            <tbody>
              {imsis.map(im => (
                <tr key={im.imsi} className="border-b border-border hover:bg-page">
                  <td className="px-4 py-3 font-mono text-xs">{im.imsi}</td>
                  <td className="px-4 py-3 text-center text-sm tabular-nums text-gray-500">{im.priority}</td>
                  <td className="px-4 py-3"><StatusBadge status={im.status} /></td>
                  {!isIccidMode && (
                    <td className="px-4 py-3">
                      {isApnMode
                        ? <ImsiApnIpsList apnIps={im.apn_ips ?? []} />
                        : <span className="font-mono text-xs text-gray-500">{im.apn_ips?.[0]?.static_ip ?? <span className="text-gray-400 not-italic">Auto</span>}</span>
                      }
                    </td>
                  )}
                  <td className="px-4 py-3 text-right space-x-3">
                    {im.status === 'active'
                      ? <button onClick={() => patchImsi(im.imsi, { status: 'suspended' })} className="text-xs text-amber-600 hover:underline">Suspend</button>
                      : <button onClick={() => patchImsi(im.imsi, { status: 'active'    })} className="text-xs text-green-600 hover:underline">Activate</button>
                    }
                    <button onClick={() => deleteImsi(im.imsi)} className="text-xs text-red-500 hover:underline">Remove</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

// ─── New Profile ──────────────────────────────────────────────────────────────
function NewProfile() {
  const navigate = useNavigate()
  const { show } = useToasts()
  const [pools,  setPools]  = useState<Pool[]>([])
  const [saving, setSaving] = useState(false)
  const [error,  setError]  = useState<string | null>(null)
  const [form, setForm] = useState({
    iccid: '', account_name: '', ip_resolution: 'imsi' as IpResolution,
    imsis: [{ imsi: '', static_ip: '', pool_id: '' }], imei: '', tags: '',
  })

  useEffect(() => {
    apiClient.get('/pools').then(r => setPools(r.data.pools ?? r.data.items ?? [])).catch(() => {})
  }, [])

  const setF = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }))
  const addRow    = () => setForm(f => ({ ...f, imsis: [...f.imsis, { imsi: '', static_ip: '', pool_id: '' }] }))
  const removeRow = (i: number) => setForm(f => ({ ...f, imsis: f.imsis.filter((_, x) => x !== i) }))
  const setRow = (i: number, k: string, v: string) =>
    setForm(f => ({ ...f, imsis: f.imsis.map((r, x) => x === i ? { ...r, [k]: v } : r) }))

  async function submit(e: React.FormEvent) {
    e.preventDefault(); setSaving(true); setError(null)
    try {
      const body: Record<string, unknown> = { ip_resolution: form.ip_resolution, status: 'active' }
      if (form.iccid)        body.iccid        = form.iccid
      if (form.account_name) body.account_name = form.account_name
      const imsis = form.imsis.filter(r => /^\d{15}$/.test(r.imsi.trim())).map(r => ({
        imsi:    r.imsi.trim(),
        apn_ips: r.static_ip || r.pool_id ? [{ apn: null, static_ip: r.static_ip || null, pool_id: r.pool_id || null }] : [],
      }))
      if (imsis.length) body.imsis = imsis
      const meta: Record<string, unknown> = {}
      if (form.imei) meta.imei = form.imei
      if (form.tags) meta.tags = form.tags.split(',').map(t => t.trim()).filter(Boolean)
      if (Object.keys(meta).length) body.metadata = meta
      const res = await apiClient.post('/profiles', body)
      show('success', `Profile created: ${res.data.sim_id}`)
      navigate(`/devices/${res.data.sim_id}`)
    } catch (e: unknown) {
      const d = (e as { response?: { data?: { error?: string } } })?.response?.data
      setError(d?.error ?? String(e))
    } finally { setSaving(false) }
  }

  const needsImsis = ['imsi', 'imsi_apn'].includes(form.ip_resolution)

  return (
    <div className="max-w-2xl space-y-4">
      <div className="flex items-center gap-2 text-sm">
        <button onClick={() => navigate('/devices')} className="text-primary hover:underline">SIMs</button>
        <span className="text-gray-400">/</span>
        <span className="text-gray-600">New Profile</span>
      </div>
      <h1 className="page-title">New SIM Profile</h1>
      {error && <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-lg">{error}</div>}

      <form onSubmit={submit} className="card p-6 space-y-5">
        <div className="grid grid-cols-2 gap-4">
          <div className="field">
            <label className="label">IP Resolution *</label>
            <select className="select" value={form.ip_resolution} onChange={e => setF('ip_resolution', e.target.value)}>
              {IP_RESOLUTIONS.map(r => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
          <div className="field">
            <label className="label">Account Name</label>
            <input className="input" placeholder="Melita" value={form.account_name} onChange={e => setF('account_name', e.target.value)} />
          </div>
          <div className="field col-span-2">
            <label className="label">ICCID (optional, 19–20 digits)</label>
            <input className="input font-mono" placeholder="8944501012345678901" value={form.iccid} onChange={e => setF('iccid', e.target.value)} />
          </div>
        </div>

        {needsImsis && (
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="label mb-0">IMSIs</span>
              <button type="button" onClick={addRow} className="text-xs text-primary hover:underline">+ Add IMSI</button>
            </div>
            <div className="space-y-2">
              {form.imsis.map((row, i) => (
                <div key={i} className="grid grid-cols-3 gap-2 items-center">
                  <input className="input font-mono text-xs" placeholder="IMSI (15 digits)"
                    value={row.imsi} onChange={e => setRow(i, 'imsi', e.target.value)} />
                  <input className="input text-xs" placeholder="Static IP (optional)"
                    value={row.static_ip} onChange={e => setRow(i, 'static_ip', e.target.value)} />
                  <div className="flex gap-1">
                    <select className="select text-xs flex-1" value={row.pool_id} onChange={e => setRow(i, 'pool_id', e.target.value)}>
                      <option value="">No pool</option>
                      {pools.map(p => <option key={p.pool_id} value={p.pool_id}>{p.name}</option>)}
                    </select>
                    {form.imsis.length > 1 && (
                      <button type="button" onClick={() => removeRow(i)} className="btn-icon text-red-400 text-lg leading-none">×</button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-4">
          <div className="field">
            <label className="label">IMEI (optional)</label>
            <input className="input font-mono text-xs" placeholder="865914030178379" value={form.imei} onChange={e => setF('imei', e.target.value)} />
          </div>
          <div className="field">
            <label className="label">Tags (comma-separated)</label>
            <input className="input text-xs" placeholder="iot, nova-project" value={form.tags} onChange={e => setF('tags', e.target.value)} />
          </div>
        </div>

        <div className="flex gap-3 pt-2 border-t border-border">
          <button type="submit" disabled={saving} className="btn-primary">{saving ? 'Creating…' : 'Create Profile'}</button>
          <button type="button" onClick={() => navigate('/devices')} className="btn-ghost">Cancel</button>
        </div>
      </form>
    </div>
  )
}

// ─── Bulk Import ──────────────────────────────────────────────────────────────
function BulkImport() {
  const navigate = useNavigate()
  const { show } = useToasts()
  const [file,    setFile]    = useState<File | null>(null)
  const [preview, setPreview] = useState<string[][]>([])
  const [headers, setHeaders] = useState<string[]>([])
  const [error,   setError]   = useState<string | null>(null)
  const [busy,    setBusy]    = useState(false)

  const REQUIRED = ['iccid', 'account_name', 'status', 'ip_resolution']

  function downloadTemplate() {
    const csv = [
      'sim_id,iccid,account_name,status,ip_resolution,imsi,apn,static_ip,pool_id',
      ',8944501012345678901,Melita,active,imsi,278773000002002,,100.65.120.5,pool-uuid-abc',
    ].join('\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
    Object.assign(document.createElement('a'), { href: url, download: 'sim-profiles-template.csv' }).click()
    URL.revokeObjectURL(url)
  }

  function handleFile(f: File) {
    setFile(f); setError(null)
    const reader = new FileReader()
    reader.onload = ev => {
      const lines = (ev.target?.result as string).split('\n').filter(Boolean)
      const h = lines[0].split(',').map(c => c.trim())
      setHeaders(h)
      const missing = REQUIRED.filter(r => !h.includes(r))
      if (missing.length) { setError(`Missing columns: ${missing.join(', ')}`); return }
      setPreview(lines.slice(1, 6).map(l => l.split(',')))
    }
    reader.readAsText(f)
  }

  async function upload() {
    if (!file) return; setBusy(true)
    try {
      const fd = new FormData(); fd.append('file', file)
      const res = await apiClient.post('/profiles/bulk', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
      show('success', `Job started: ${res.data.job_id}`)
      navigate('/bulk-jobs')
    } catch (e) { setError(String(e)) } finally { setBusy(false) }
  }

  return (
    <div className="max-w-2xl space-y-4">
      <div className="flex items-center gap-2 text-sm">
        <button onClick={() => navigate('/devices')} className="text-primary hover:underline">SIMs</button>
        <span className="text-gray-400">/</span>
        <span className="text-gray-600">Bulk Import</span>
      </div>
      <h1 className="page-title">Bulk Import</h1>

      <div className="card p-6 space-y-6">
        <div>
          <p className="text-sm font-medium text-gray-700 mb-2">Step 1 — Download template</p>
          <button onClick={downloadTemplate} className="btn-outline">↓ Download CSV Template</button>
        </div>
        <div>
          <p className="text-sm font-medium text-gray-700 mb-2">Step 2 — Upload your file</p>
          <label className="flex flex-col items-center justify-center h-32 border-2 border-dashed border-border rounded-lg bg-page cursor-pointer hover:border-primary transition-colors">
            <span className="text-gray-500 text-sm">{file ? file.name : 'Drag & drop CSV here, or click to browse'}</span>
            <span className="text-gray-400 text-xs mt-1">Max 100,000 rows · .csv only</span>
            <input type="file" accept=".csv" className="hidden" onChange={e => { if (e.target.files?.[0]) handleFile(e.target.files[0]) }} />
          </label>
        </div>
        {error && <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-lg">{error}</div>}
        {preview.length > 0 && (
          <div>
            <p className="text-sm font-medium text-gray-700 mb-2">Step 3 — Preview (first {preview.length} rows)</p>
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="text-xs w-full">
                <thead className="bg-page border-b border-border">
                  <tr>{headers.slice(0, 8).map(h => <th key={h} className="px-2 py-2 text-left text-gray-500 font-semibold uppercase tracking-wide">{h}</th>)}</tr>
                </thead>
                <tbody className="divide-y divide-border bg-white">
                  {preview.map((row, i) => (
                    <tr key={i}>{row.slice(0, 8).map((v, j) => <td key={j} className="px-2 py-1.5 font-mono">{v || '—'}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
        <div className="flex gap-3 pt-2 border-t border-border">
          <button onClick={() => navigate('/devices')} className="btn-ghost">Cancel</button>
          <button onClick={upload} disabled={!file || !!error || busy} className="btn-primary ml-auto">
            {busy ? 'Uploading…' : 'Upload & Import'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Router ───────────────────────────────────────────────────────────────────
export default function Devices() {
  return (
    <Routes>
      <Route index            element={<DeviceList />} />
      <Route path="new"       element={<NewProfile />} />
      <Route path="bulk"      element={<BulkImport />} />
      <Route path=":sim_id" element={<ProfileDetail />} />
    </Routes>
  )
}
