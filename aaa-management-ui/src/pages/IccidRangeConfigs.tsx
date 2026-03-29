import { Fragment, useEffect, useState } from 'react'
import { Routes, Route, useNavigate, useParams } from 'react-router-dom'
import { apiClient } from '../apiClient'
import StatusBadge from '../components/StatusBadge'
import { useToasts } from '../stores/toast'
import type { IccidRangeConfig, ImsiSlot, Pool, ApnPool, IpResolution, ProvisioningMode } from '../types'

const IP_RES_LABELS: Record<IpResolution, string> = {
  imsi:     'IMSI',
  imsi_apn: 'IMSI + APN',
  iccid:    'ICCID',
  iccid_apn:'ICCID + APN',
}

// ─── ICCID Range Config List ──────────────────────────────────────────────────
function IccidRangeConfigList() {
  const navigate    = useNavigate()
  const { show }    = useToasts()
  const [configs,   setConfigs]  = useState<IccidRangeConfig[]>([])
  const [loading,   setLoading]  = useState(true)
  const [error,     setError]    = useState<string | null>(null)
  const [showNew,   setShowNew]  = useState(false)
  const [slotCounts, setSlotCounts] = useState<Record<number, number>>({})

  async function load() {
    setLoading(true)
    try {
      const res = await apiClient.get('/iccid-range-configs')
      const list: IccidRangeConfig[] = res.data.items ?? res.data.configs ?? res.data ?? []
      setConfigs(list)

      // Fetch IMSI slot counts for each config
      const slotRes = await Promise.allSettled(
        list.map(async c => {
          const r = await apiClient.get(`/iccid-range-configs/${c.id}/imsi-slots`)
          const slots: ImsiSlot[] = r.data.items ?? r.data.slots ?? r.data ?? []
          return { id: c.id, count: slots.length }
        })
      )
      const counts: Record<number, number> = {}
      slotRes.forEach(r => { if (r.status === 'fulfilled') counts[r.value.id] = r.value.count })
      setSlotCounts(counts)
    } catch (e) { setError(String(e)) } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  async function createConfig(form: NewIccidConfigForm, slotDrafts: ImsiSlotDraft[], cardApnPools: ApnPoolDraft[]) {
    try {
      const res = await apiClient.post('/iccid-range-configs', {
        account_name:      form.account_name || null,
        f_iccid:           form.f_iccid,
        t_iccid:           form.t_iccid,
        pool_id:           form.pool_id || null,
        ip_resolution:     form.ip_resolution,
        imsi_count:        form.imsi_count,
        description:       form.description || null,
        provisioning_mode: form.provisioning_mode,
      })
      const iccidRangeId: number = res.data.id

      // Add IMSI slots sequentially; last slot triggers provisioning for immediate mode
      let jobId: string | null = null
      for (let i = 0; i < slotDrafts.length; i++) {
        const slot = slotDrafts[i]
        if (!slot.f_imsi || !slot.t_imsi) continue
        const slotNum = i + 1
        const slotRes = await apiClient.post(`/iccid-range-configs/${iccidRangeId}/imsi-slots`, {
          imsi_slot: slotNum,
          f_imsi:    slot.f_imsi,
          t_imsi:    slot.t_imsi,
          pool_id:   slot.pool_id || null,
        })
        if (slotRes.data.job_id) jobId = slotRes.data.job_id
        // For imsi_apn: POST each slot's APN→pool entries
        if (form.ip_resolution === 'imsi_apn') {
          for (const ap of slot.apn_pools) {
            if (ap.apn && ap.pool_id) {
              await apiClient.post(`/iccid-range-configs/${iccidRangeId}/imsi-slots/${slotNum}/apn-pools`, {
                apn: ap.apn, pool_id: ap.pool_id,
              })
            }
          }
        }
      }
      // For iccid_apn: POST card-level APN→pool entries to slot 1
      if (form.ip_resolution === 'iccid_apn') {
        for (const ap of cardApnPools) {
          if (ap.apn && ap.pool_id) {
            await apiClient.post(`/iccid-range-configs/${iccidRangeId}/imsi-slots/1/apn-pools`, {
              apn: ap.apn, pool_id: ap.pool_id,
            }).catch(() => {}) // slot 1 may not exist yet in first_connect mode
          }
        }
      }

      if (jobId) {
        show('success', `Created — provisioning job ${jobId} started`)
        setShowNew(false)
        navigate('/bulk-jobs')
      } else {
        show('success', 'ICCID range config created')
        setShowNew(false); load()
      }
    } catch (e) { show('error', String(e)) }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs text-gray-400 uppercase tracking-widest font-medium">Configuration</p>
          <h1 className="page-title">ICCID Range Configs</h1>
        </div>
        <button onClick={() => setShowNew(true)} className="btn-primary">+ New Config</button>
      </div>

      {error && <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-lg">{error}</div>}
      {showNew && <NewIccidConfigModal onClose={() => setShowNew(false)} onSave={(f, s, c) => createConfig(f, s, c)} />}

      <div className="tbl-wrap">
        {loading ? (
          <div className="flex items-center justify-center h-40 text-gray-400 text-sm">Loading…</div>
        ) : configs.length === 0 ? (
          <div className="flex items-center justify-center h-40 text-gray-400 text-sm">No ICCID range configs configured.</div>
        ) : (
          <table className="tbl">
            <thead><tr>
              <th>ID</th><th>Account</th><th>ICCID Range</th><th>Pool</th>
              <th>IP Resolution</th><th className="text-center">IMSI Count</th>
              <th className="text-center">IMSI Slots</th><th>Mode</th><th>Status</th><th />
            </tr></thead>
            <tbody>
              {configs.map(c => (
                <tr key={c.id}
                  className="border-b border-border hover:bg-page transition-colors cursor-pointer"
                  onClick={() => navigate(String(c.id))}>
                  <td className="px-4 py-3 font-mono text-xs text-gray-500">#{c.id}</td>
                  <td className="px-4 py-3 text-sm">{c.account_name ?? <span className="text-gray-300">—</span>}</td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-700">
                    <span className="text-gray-400">{c.f_iccid}</span>
                    <span className="mx-1 text-gray-300">→</span>
                    <span className="text-gray-400">{c.t_iccid}</span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">{c.pool_name ?? c.pool_id ?? <span className="text-gray-300">—</span>}</td>
                  <td className="px-4 py-3">
                    <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full font-medium">
                      {IP_RES_LABELS[c.ip_resolution]}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-center text-sm tabular-nums text-gray-600">
                    {c.imsi_count ?? '—'}
                  </td>
                  <td className="px-4 py-3 text-center text-sm tabular-nums text-gray-600">
                    {slotCounts[c.id] ?? '—'}
                  </td>
                  <td className="px-4 py-3">
                    {c.provisioning_mode === 'immediate'
                      ? <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full font-medium">Immediate</span>
                      : <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full font-medium">First Connect</span>}
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

// ─── ICCID Range Config Detail ────────────────────────────────────────────────
function IccidRangeConfigDetail() {
  const { id }    = useParams<{ id: string }>()
  const navigate  = useNavigate()
  const { show }  = useToasts()
  const [config,   setConfig]  = useState<IccidRangeConfig | null>(null)
  const [slots,    setSlots]   = useState<ImsiSlot[]>([])
  const [pools,    setPools]   = useState<Pool[]>([])
  const [loading,  setLoading] = useState(true)
  const [error,    setError]   = useState<string | null>(null)
  const [editing,  setEditing] = useState(false)
  const [editForm, setEditForm] = useState<Partial<IccidRangeConfig>>({})
  const [addingSlot, setAddingSlot] = useState(false)
  const [slotForm,   setSlotForm]   = useState({ imsi_slot: '', f_imsi: '', t_imsi: '', pool_id: '' })
  const [editSlotId,  setEditSlotId]  = useState<number | null>(null)
  const [editSlotForm, setEditSlotForm] = useState({ pool_id: '' })
  const [slotApnPools, setSlotApnPools] = useState<Record<number, ApnPool[]>>({})
  const [managingApnSlot, setManagingApnSlot] = useState<number | null>(null)
  const [apnForms, setApnForms] = useState<Record<number, { apn: string; pool_id: string }>>({})

  async function load() {
    if (!id) return; setLoading(true)
    try {
      const [cr, sr] = await Promise.all([
        apiClient.get(`/iccid-range-configs/${id}`),
        apiClient.get(`/iccid-range-configs/${id}/imsi-slots`),
      ])
      setConfig(cr.data)
      setSlots(sr.data.items ?? sr.data.slots ?? sr.data ?? [])
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
      await apiClient.patch(`/iccid-range-configs/${id}`, editForm)
      show('success', 'Config updated'); setEditing(false); load()
    } catch (e) { show('error', String(e)) }
  }

  async function deleteConfig() {
    if (!confirm('Delete this ICCID range config?')) return
    try {
      await apiClient.delete(`/iccid-range-configs/${id}`)
      show('success', 'Config deleted'); navigate('/iccid-range-configs')
    } catch (e) { show('error', String(e)) }
  }

  async function addSlot() {
    if (!slotForm.imsi_slot || !slotForm.f_imsi || !slotForm.t_imsi) return
    try {
      const res = await apiClient.post(`/iccid-range-configs/${id}/imsi-slots`, {
        imsi_slot: Number(slotForm.imsi_slot),
        f_imsi:    slotForm.f_imsi,
        t_imsi:    slotForm.t_imsi,
        pool_id:   slotForm.pool_id || null,
      })
      if (res.data.job_id) {
        show('success', `Last slot added — provisioning job ${res.data.job_id} started`)
        navigate('/bulk-jobs')
      } else {
        show('success', 'IMSI slot added')
        setSlotForm({ imsi_slot: '', f_imsi: '', t_imsi: '', pool_id: '' })
        setAddingSlot(false); load()
      }
    } catch (e) { show('error', String(e)) }
  }

  async function updateSlot(slotNum: number) {
    try {
      await apiClient.patch(`/iccid-range-configs/${id}/imsi-slots/${slotNum}`, {
        pool_id: editSlotForm.pool_id || null,
      })
      show('success', 'Slot updated'); setEditSlotId(null); load()
    } catch (e) { show('error', String(e)) }
  }

  async function deleteSlot(slotNum: number) {
    if (!confirm(`Delete IMSI slot #${slotNum}?`)) return
    try {
      await apiClient.delete(`/iccid-range-configs/${id}/imsi-slots/${slotNum}`)
      show('success', 'Slot deleted'); load()
    } catch (e) { show('error', String(e)) }
  }

  async function loadSlotApnPools(slotNum: number) {
    try {
      const r = await apiClient.get(`/iccid-range-configs/${id}/imsi-slots/${slotNum}/apn-pools`)
      const pools: ApnPool[] = r.data.items ?? r.data ?? []
      setSlotApnPools(prev => ({ ...prev, [slotNum]: pools }))
    } catch (e) { show('error', String(e)) }
  }

  function toggleManageApn(slotNum: number) {
    if (managingApnSlot === slotNum) {
      setManagingApnSlot(null)
    } else {
      setManagingApnSlot(slotNum)
      if (!slotApnPools[slotNum]) loadSlotApnPools(slotNum)
      if (!apnForms[slotNum]) setApnForms(prev => ({ ...prev, [slotNum]: { apn: '', pool_id: '' } }))
    }
  }

  async function addSlotApnPool(slotNum: number) {
    const form = apnForms[slotNum]
    if (!form?.apn || !form?.pool_id) return
    try {
      await apiClient.post(`/iccid-range-configs/${id}/imsi-slots/${slotNum}/apn-pools`, {
        apn: form.apn, pool_id: form.pool_id,
      })
      show('success', 'APN pool added')
      setApnForms(prev => ({ ...prev, [slotNum]: { apn: '', pool_id: '' } }))
      loadSlotApnPools(slotNum)
    } catch (e) { show('error', String(e)) }
  }

  async function removeSlotApnPool(slotNum: number, apn: string) {
    if (!confirm(`Remove APN override for "${apn}" on slot ${slotNum}?`)) return
    try {
      await apiClient.delete(`/iccid-range-configs/${id}/imsi-slots/${slotNum}/apn-pools/${encodeURIComponent(apn)}`)
      show('success', 'APN pool removed')
      loadSlotApnPools(slotNum)
    } catch (e) { show('error', String(e)) }
  }

  // Live cardinality check: slot IMSI range must be consistent with parent ICCID count
  function slotCardinalityOk(): { ok: boolean; msg: string } {
    const { f_imsi, t_imsi } = slotForm
    if (!f_imsi || !t_imsi) return { ok: true, msg: '' }
    const fBig = BigInt(f_imsi), tBig = BigInt(t_imsi)
    if (tBig < fBig) return { ok: false, msg: 'To IMSI must be ≥ From IMSI' }
    const count = Number(tBig - fBig + BigInt(1))
    if (config && count !== config.imsi_count && config.imsi_count > 0) {
      return { ok: false, msg: `Range has ${count} IMSIs but config expects ${config.imsi_count}` }
    }
    return { ok: true, msg: count > 0 ? `${count} IMSIs in range` : '' }
  }

  if (loading) return <div className="flex items-center justify-center h-60 text-gray-400 text-sm">Loading…</div>
  if (error)   return <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">{error}</div>
  if (!config) return null

  const cardinality = slotCardinalityOk()

  return (
    <div className="space-y-4 max-w-4xl">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm">
        <button onClick={() => navigate('/iccid-range-configs')} className="text-primary hover:underline">ICCID Range Configs</button>
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
                    <input className="input text-sm" value={editForm.account_name ?? ''}
                      onChange={e => setEditForm(f => ({ ...f, account_name: e.target.value }))} />
                  </div>
                  <div className="field">
                    <label className="label">Description</label>
                    <input className="input text-sm" value={editForm.description ?? ''}
                      onChange={e => setEditForm(f => ({ ...f, description: e.target.value }))} />
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
                    <label className="label">Default Pool</label>
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
                  <h2 className="text-lg font-semibold text-gray-900">ICCID Range Config #{config.id}</h2>
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
            { l: 'Account',      v: config.account_name ?? '—' },
            { l: 'From ICCID',   v: config.f_iccid },
            { l: 'To ICCID',     v: config.t_iccid },
            { l: 'Default Pool', v: config.pool_name ?? config.pool_id ?? '—' },
            { l: 'IP Resolution', v: IP_RES_LABELS[config.ip_resolution] },
            { l: 'IMSI Count',   v: String(config.imsi_count ?? '—') },
            { l: 'Mode',         v: config.provisioning_mode === 'immediate' ? 'Immediate' : 'First Connect' },
          ].map(f => (
            <div key={f.l}>
              <p className="text-xs text-gray-400 uppercase tracking-wide font-medium mb-0.5">{f.l}</p>
              <p className="font-mono text-sm text-gray-800">{f.v}</p>
            </div>
          ))}
        </div>
      </div>

      {/* IMSI Slot Manager */}
      <div className="card p-6 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-gray-900">IMSI Slots</h3>
            <p className="text-xs text-gray-400 mt-0.5">
              Each ICCID in the range hosts one SIM. Each SIM slot maps to an IMSI sub-range and optional per-slot pool.
            </p>
          </div>
          {!addingSlot && (
            <button onClick={() => setAddingSlot(true)} className="btn-outline text-xs py-1.5 px-3">
              + Add Slot
            </button>
          )}
        </div>

        {/* Slot table */}
        {slots.length === 0 && !addingSlot ? (
          <p className="text-sm text-gray-400 italic">No IMSI slots configured yet.</p>
        ) : (
          <table className="tbl">
            <thead><tr>
              <th className="text-center">Slot #</th>
              <th>From IMSI</th>
              <th>To IMSI</th>
              <th>Pool Override</th>
              {(config.ip_resolution === 'imsi_apn' || config.ip_resolution === 'iccid_apn') && (
                <th>APN Pools</th>
              )}
              <th />
            </tr></thead>
            <tbody>
              {slots.map(s => (
                <Fragment key={s.id}>
                <tr className="border-b border-border">
                  <td className="px-4 py-2.5 text-center font-mono text-xs text-gray-500">{s.imsi_slot}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-gray-700">{s.f_imsi}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-gray-700">{s.t_imsi}</td>
                  <td className="px-4 py-2.5 text-sm text-gray-600">
                    {editSlotId === s.id ? (
                      <div className="flex items-center gap-2">
                        <select className="select text-xs py-1" value={editSlotForm.pool_id}
                          onChange={e => setEditSlotForm({ pool_id: e.target.value })}>
                          <option value="">— inherit default —</option>
                          {pools.map(p => <option key={p.pool_id} value={p.pool_id}>{p.name}</option>)}
                        </select>
                        <button onClick={() => updateSlot(s.imsi_slot)} className="btn-primary text-xs py-1 px-2">Save</button>
                        <button onClick={() => setEditSlotId(null)} className="btn-ghost text-xs py-1">✕</button>
                      </div>
                    ) : (
                      s.pool_name ?? s.pool_id ?? <span className="text-gray-300">— default —</span>
                    )}
                  </td>
                  {(config.ip_resolution === 'imsi_apn' || config.ip_resolution === 'iccid_apn') && (
                    <td className="px-4 py-2.5">
                      <button
                        onClick={() => toggleManageApn(s.imsi_slot)}
                        className="text-xs text-primary hover:underline flex items-center gap-1">
                        {managingApnSlot === s.imsi_slot ? 'Hide' : (
                          <>
                            {slotApnPools[s.imsi_slot]?.length
                              ? <span className="bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded-full font-mono">{slotApnPools[s.imsi_slot].length}</span>
                              : null}
                            Manage APNs
                          </>
                        )}
                      </button>
                    </td>
                  )}
                  <td className="px-4 py-2.5 text-right">
                    {editSlotId !== s.id && (
                      <div className="flex items-center justify-end gap-3">
                        <button
                          onClick={() => { setEditSlotId(s.id); setEditSlotForm({ pool_id: s.pool_id ?? '' }) }}
                          className="text-xs text-primary hover:underline">
                          Edit
                        </button>
                        <button
                          onClick={() => deleteSlot(s.imsi_slot)}
                          className="text-xs text-red-500 hover:text-red-700">
                          Remove
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
                {managingApnSlot === s.imsi_slot && (
                  <tr className="bg-blue-50/50">
                    <td colSpan={config.ip_resolution === 'imsi_apn' || config.ip_resolution === 'iccid_apn' ? 6 : 5}
                      className="px-6 py-3">
                      {config.ip_resolution === 'iccid_apn' && s.imsi_slot !== 1 && (
                        <p className="text-xs text-amber-600 mb-2">
                          Card-level — only Slot 1 APN pools affect IP allocation for <code>iccid_apn</code> mode.
                        </p>
                      )}
                      <div className="space-y-2">
                        {/* Existing APN overrides */}
                        {slotApnPools[s.imsi_slot]?.length ? (
                          <table className="w-full text-xs">
                            <thead><tr className="text-gray-400 uppercase tracking-wide">
                              <th className="text-left py-1 pr-4 font-medium">APN</th>
                              <th className="text-left py-1 pr-4 font-medium">Pool</th>
                              <th />
                            </tr></thead>
                            <tbody>
                              {slotApnPools[s.imsi_slot].map(ap => (
                                <tr key={ap.id} className="border-t border-border/50">
                                  <td className="py-1.5 pr-4 font-mono">{ap.apn}</td>
                                  <td className="py-1.5 pr-4 text-gray-600">
                                    {ap.pool_name ?? ap.pool_id}
                                  </td>
                                  <td className="py-1.5 text-right">
                                    <button
                                      onClick={() => removeSlotApnPool(s.imsi_slot, ap.apn)}
                                      className="text-red-500 hover:text-red-700">
                                      Remove
                                    </button>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        ) : (
                          <p className="text-xs text-gray-400 italic">No APN pool overrides for this slot.</p>
                        )}
                        {/* Add new APN override */}
                        <div className="flex items-center gap-2 pt-1">
                          <input
                            className="input text-xs py-1 font-mono w-36"
                            placeholder="APN (e.g. internet)"
                            value={apnForms[s.imsi_slot]?.apn ?? ''}
                            onChange={e => setApnForms(prev => ({
                              ...prev, [s.imsi_slot]: { ...prev[s.imsi_slot], apn: e.target.value }
                            }))} />
                          <select
                            className="select text-xs py-1 flex-1"
                            value={apnForms[s.imsi_slot]?.pool_id ?? ''}
                            onChange={e => setApnForms(prev => ({
                              ...prev, [s.imsi_slot]: { ...prev[s.imsi_slot], pool_id: e.target.value }
                            }))}>
                            <option value="">— select pool —</option>
                            {pools.map(p => <option key={p.pool_id} value={p.pool_id}>{p.name}</option>)}
                          </select>
                          <button
                            onClick={() => addSlotApnPool(s.imsi_slot)}
                            disabled={!apnForms[s.imsi_slot]?.apn || !apnForms[s.imsi_slot]?.pool_id}
                            className="btn-primary text-xs py-1 px-3">
                            Add
                          </button>
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
                </Fragment>
              ))}

              {/* Add slot inline row */}
              {addingSlot && (
                <tr className="border-b border-border bg-primary/5">
                  <td className="px-4 py-2.5">
                    <input className="input text-xs py-1 w-16 text-center font-mono" type="number" min="1"
                      placeholder="1" value={slotForm.imsi_slot}
                      onChange={e => setSlotForm(f => ({ ...f, imsi_slot: e.target.value }))} />
                  </td>
                  <td className="px-4 py-2.5">
                    <input className="input text-xs py-1 font-mono" placeholder="310260000000000"
                      value={slotForm.f_imsi}
                      onChange={e => setSlotForm(f => ({ ...f, f_imsi: e.target.value }))} />
                  </td>
                  <td className="px-4 py-2.5">
                    <input className="input text-xs py-1 font-mono" placeholder="310260000099999"
                      value={slotForm.t_imsi}
                      onChange={e => setSlotForm(f => ({ ...f, t_imsi: e.target.value }))} />
                  </td>
                  <td className="px-4 py-2.5">
                    <select className="select text-xs py-1" value={slotForm.pool_id}
                      onChange={e => setSlotForm(f => ({ ...f, pool_id: e.target.value }))}>
                      <option value="">— inherit default —</option>
                      {pools.map(p => <option key={p.pool_id} value={p.pool_id}>{p.name}</option>)}
                    </select>
                  </td>
                  {(config.ip_resolution === 'imsi_apn' || config.ip_resolution === 'iccid_apn') && (
                    <td className="px-4 py-2.5" />
                  )}
                  <td className="px-4 py-2.5 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        onClick={addSlot}
                        disabled={!slotForm.imsi_slot || !slotForm.f_imsi || !slotForm.t_imsi}
                        className="btn-primary text-xs py-1 px-3">
                        Add
                      </button>
                      <button onClick={() => setAddingSlot(false)} className="btn-ghost text-xs py-1">Cancel</button>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}

        {/* Cardinality hint */}
        {addingSlot && slotForm.f_imsi && slotForm.t_imsi && (
          <p className={`text-xs ${cardinality.ok ? 'text-green-700' : 'text-red-600'}`}>
            {cardinality.ok ? '✓' : '✗'} {cardinality.msg}
          </p>
        )}
      </div>
    </div>
  )
}

// ─── New ICCID Range Config Modal ─────────────────────────────────────────────
type NewIccidConfigForm = {
  account_name:      string
  f_iccid:           string
  t_iccid:           string
  pool_id:           string
  ip_resolution:     IpResolution
  imsi_count:        number   // IMSI slots per SIM card (1–10); NOT the number of cards in the range
  description:       string
  provisioning_mode: ProvisioningMode
}

type ApnPoolDraft = { apn: string; pool_id: string }
type ImsiSlotDraft = { f_imsi: string; t_imsi: string; pool_id: string; apn_pools: ApnPoolDraft[] }

function NewIccidConfigModal({
  onClose, onSave,
}: { onClose: () => void; onSave: (f: NewIccidConfigForm, slots: ImsiSlotDraft[], cardApnPools: ApnPoolDraft[]) => void }) {
  const [form, setForm] = useState<NewIccidConfigForm>({
    account_name: '', f_iccid: '', t_iccid: '', pool_id: '',
    ip_resolution: 'iccid', imsi_count: 1, description: '',
    provisioning_mode: 'first_connect',
  })
  const [iccidCount, setIccidCount] = useState<string>('')
  const [slotDrafts, setSlotDrafts] = useState<ImsiSlotDraft[]>([{ f_imsi: '', t_imsi: '', pool_id: '', apn_pools: [] }])
  const [cardApnPools, setCardApnPools] = useState<ApnPoolDraft[]>([])
  const [pools, setPools] = useState<Pool[]>([])

  const setF = <K extends keyof NewIccidConfigForm>(k: K, v: NewIccidConfigForm[K]) =>
    setForm(f => ({ ...f, [k]: v }))

  function setIccidField(key: 'f_iccid' | 't_iccid', val: string) {
    setForm(f => {
      const next = { ...f, [key]: val }
      try {
        if (next.f_iccid && next.t_iccid) {
          const count = BigInt(next.t_iccid) - BigInt(next.f_iccid) + 1n
          setIccidCount(count > 0n ? count.toString() : '')
        } else { setIccidCount('') }
      } catch { setIccidCount('') }
      return next
    })
  }

  function setImsiCount(n: number) {
    const clamped = Math.max(1, Math.min(10, n || 1))
    setF('imsi_count', clamped)
    setSlotDrafts(prev => {
      const next = [...prev]
      while (next.length < clamped) next.push({ f_imsi: '', t_imsi: '', pool_id: '', apn_pools: [] })
      return next.slice(0, clamped)
    })
  }

  function setSlotField(i: number, key: 'f_imsi' | 't_imsi' | 'pool_id', val: string) {
    setSlotDrafts(prev => prev.map((s, idx) => idx === i ? { ...s, [key]: val } : s))
  }

  function setSlotApnCount(i: number, count: number) {
    const n = Math.max(0, Math.min(10, count || 0))
    setSlotDrafts(prev => prev.map((s, idx) => {
      if (idx !== i) return s
      const next = [...s.apn_pools]
      while (next.length < n) next.push({ apn: '', pool_id: '' })
      return { ...s, apn_pools: next.slice(0, n) }
    }))
  }

  function setSlotApnPool(i: number, j: number, key: keyof ApnPoolDraft, val: string) {
    setSlotDrafts(prev => prev.map((s, idx) => {
      if (idx !== i) return s
      const apn_pools = s.apn_pools.map((ap, ai) => ai === j ? { ...ap, [key]: val } : ap)
      return { ...s, apn_pools }
    }))
  }

  function setCardApnCount(count: number) {
    const n = Math.max(0, Math.min(10, count || 0))
    setCardApnPools(prev => {
      const next = [...prev]
      while (next.length < n) next.push({ apn: '', pool_id: '' })
      return next.slice(0, n)
    })
  }

  function setCardApnPool(j: number, key: keyof ApnPoolDraft, val: string) {
    setCardApnPools(prev => prev.map((ap, ai) => ai === j ? { ...ap, [key]: val } : ap))
  }

  useEffect(() => {
    apiClient.get('/pools').then(r => setPools(r.data.pools ?? r.data.items ?? [])).catch(() => {})
  }, [])

  const immediateSlotsMissing = form.provisioning_mode === 'immediate' &&
    slotDrafts.some(s => !s.f_imsi || !s.t_imsi)
  const canSubmit = !!form.f_iccid && !!form.t_iccid && !immediateSlotsMissing

  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 overflow-y-auto">
        <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg my-4">
          <div className="flex items-center justify-between px-6 py-4 border-b border-border">
            <h2 className="text-base font-semibold">New ICCID Range Config</h2>
            <button onClick={onClose} className="btn-icon text-xl leading-none">×</button>
          </div>
          <div className="px-6 py-5 space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="field">
                <label className="label">From ICCID *</label>
                <input className="input font-mono text-sm" placeholder="8901260000000000000"
                  value={form.f_iccid} onChange={e => setIccidField('f_iccid', e.target.value)} />
              </div>
              <div className="field">
                <label className="label">To ICCID *</label>
                <input className="input font-mono text-sm" placeholder="8901260000000099999"
                  value={form.t_iccid} onChange={e => setIccidField('t_iccid', e.target.value)} />
              </div>
            </div>
            <div className="grid grid-cols-3 gap-4">
              <div className="field col-span-2">
                <label className="label">Account Name</label>
                <input className="input text-sm" placeholder="Operator A"
                  value={form.account_name} onChange={e => setF('account_name', e.target.value)} />
              </div>
              <div className="field">
                <label className="label">ICCID Count</label>
                <input className="input text-sm bg-gray-50 text-gray-500 cursor-default" readOnly
                  value={iccidCount || '—'} tabIndex={-1} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="field">
                <label className="label">IP Resolution *</label>
                <select className="select text-sm" value={form.ip_resolution}
                  onChange={e => setF('ip_resolution', e.target.value as IpResolution)}>
                  {(Object.entries(IP_RES_LABELS) as [IpResolution, string][]).map(([v, l]) => (
                    <option key={v} value={v}>{l}</option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label className="label">
                  {form.ip_resolution === 'iccid' ? 'IP Pool' : 'Default Pool'}
                </label>
                <select className="select text-sm" value={form.pool_id}
                  onChange={e => setF('pool_id', e.target.value)}>
                  <option value="">— none —</option>
                  {pools.map(p => <option key={p.pool_id} value={p.pool_id}>{p.name}</option>)}
                </select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="field">
                <label className="label">IMSI Slots per Card</label>
                <input className="input text-sm" type="number" min="1" max="10"
                  value={form.imsi_count}
                  onChange={e => setImsiCount(parseInt(e.target.value, 10))} />
              </div>
              <div className="field">
                <label className="label">Provisioning Mode</label>
                <select className="select text-sm" value={form.provisioning_mode}
                  onChange={e => setF('provisioning_mode', e.target.value as ProvisioningMode)}>
                  <option value="first_connect">First Connect (lazy)</option>
                  <option value="immediate">Immediate (pre-provision all SIMs)</option>
                </select>
              </div>
            </div>
            {form.provisioning_mode === 'immediate' && (
              <p className="text-xs text-blue-600 bg-blue-50 px-3 py-2 rounded">
                All SIMs will be provisioned when all IMSI slots are added below.
                The pool must have enough free IPs. Monitor progress in <strong>Bulk Jobs</strong>.
              </p>
            )}

            {/* IMSI Slots */}
            <div className="field">
              <label className="label">
                IMSI Slots
                {form.provisioning_mode === 'immediate'
                  ? <span className="text-red-500 ml-1">*</span>
                  : <span className="text-gray-400 ml-1 font-normal">(optional — can add later)</span>}
              </label>
              <div className="space-y-3 mt-1">
                {slotDrafts.map((slot, i) => (
                  <div key={i} className="rounded-lg border border-border p-3 space-y-2">
                    {/* Slot header: label + IMSI range */}
                    <div className={`grid gap-2 items-center ${form.ip_resolution === 'imsi' ? 'grid-cols-[3rem_1fr_1fr_1fr]' : 'grid-cols-[3rem_1fr_1fr]'}`}>
                      <span className="text-xs font-medium text-gray-500 text-center">S{i + 1}</span>
                      <input className="input font-mono text-xs" placeholder="From IMSI"
                        value={slot.f_imsi}
                        onChange={e => setSlotField(i, 'f_imsi', e.target.value)} />
                      <input className="input font-mono text-xs" placeholder="To IMSI"
                        value={slot.t_imsi}
                        onChange={e => setSlotField(i, 't_imsi', e.target.value)} />
                      {form.ip_resolution === 'imsi' && (
                        <select className="select text-xs" value={slot.pool_id}
                          onChange={e => setSlotField(i, 'pool_id', e.target.value)}>
                          <option value="">— IP Pool —</option>
                          {pools.map(p => <option key={p.pool_id} value={p.pool_id}>{p.name}</option>)}
                        </select>
                      )}
                    </div>
                    {/* Per-slot APN → Pool rows for imsi_apn */}
                    {form.ip_resolution === 'imsi_apn' && (
                      <div className="pl-10 space-y-1.5">
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-gray-400">APNs:</span>
                          <input type="number" min="0" max="10"
                            className="input text-xs py-0.5 w-16 text-center"
                            value={slot.apn_pools.length}
                            onChange={e => setSlotApnCount(i, parseInt(e.target.value, 10))} />
                        </div>
                        {slot.apn_pools.map((ap, j) => (
                          <div key={j} className="grid grid-cols-[1fr_1fr] gap-2">
                            <input className="input font-mono text-xs" placeholder={`APN ${j + 1}`}
                              value={ap.apn}
                              onChange={e => setSlotApnPool(i, j, 'apn', e.target.value)} />
                            <select className="select text-xs" value={ap.pool_id}
                              onChange={e => setSlotApnPool(i, j, 'pool_id', e.target.value)}>
                              <option value="">— IP Pool —</option>
                              {pools.map(p => <option key={p.pool_id} value={p.pool_id}>{p.name}</option>)}
                            </select>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* Card-level APN pools for iccid_apn */}
            {form.ip_resolution === 'iccid_apn' && (
              <div className="field">
                <label className="label">APN Pools</label>
                <p className="text-xs text-gray-400 mb-2">
                  Card-level IP allocation — one IP per APN per SIM card.
                </p>
                <div className="space-y-1.5">
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-400">APNs:</span>
                    <input type="number" min="0" max="10"
                      className="input text-xs py-0.5 w-16 text-center"
                      value={cardApnPools.length}
                      onChange={e => setCardApnCount(parseInt(e.target.value, 10))} />
                  </div>
                  {cardApnPools.map((ap, j) => (
                    <div key={j} className="grid grid-cols-[1fr_1fr] gap-2">
                      <input className="input font-mono text-xs" placeholder={`APN ${j + 1}`}
                        value={ap.apn}
                        onChange={e => setCardApnPool(j, 'apn', e.target.value)} />
                      <select className="select text-xs" value={ap.pool_id}
                        onChange={e => setCardApnPool(j, 'pool_id', e.target.value)}>
                        <option value="">— IP Pool —</option>
                        {pools.map(p => <option key={p.pool_id} value={p.pool_id}>{p.name}</option>)}
                      </select>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="field">
              <label className="label">Description</label>
              <input className="input text-sm" placeholder="Optional note"
                value={form.description} onChange={e => setF('description', e.target.value)} />
            </div>
            <div className="flex gap-3 pt-2 border-t border-border">
              <button onClick={onClose} className="btn-ghost">Cancel</button>
              <button
                onClick={() => onSave(form, slotDrafts, cardApnPools)}
                disabled={!canSubmit}
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
export default function IccidRangeConfigs() {
  return (
    <Routes>
      <Route index      element={<IccidRangeConfigList />} />
      <Route path=":id" element={<IccidRangeConfigDetail />} />
    </Routes>
  )
}
