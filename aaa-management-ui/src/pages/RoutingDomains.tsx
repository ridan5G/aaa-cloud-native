/**
 * RoutingDomains.tsx — Routing Domain CRUD + free-CIDR suggestion tool.
 *
 * Routes:
 *   /routing-domains          → RoutingDomainList
 *   /routing-domains/:id      → RoutingDomainDetail
 */
import { useEffect, useState } from 'react'
import { Routes, Route, useNavigate, useParams } from 'react-router-dom'
import { apiClient } from '../apiClient'
import { useToasts } from '../stores/toast'
import type { RoutingDomain, SuggestCidrResult } from '../types'

// ─── Helpers ─────────────────────────────────────────────────────────────────

function PrefixChip({ prefix, onRemove }: { prefix: string; onRemove?: () => void }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2 py-0.5 text-xs font-mono text-blue-700 ring-1 ring-blue-200">
      {prefix}
      {onRemove && (
        <button onClick={onRemove} className="text-blue-400 hover:text-blue-600 leading-none ml-0.5">×</button>
      )}
    </span>
  )
}

// ─── RoutingDomainList ────────────────────────────────────────────────────────
function RoutingDomainList() {
  const navigate = useNavigate()
  const { show } = useToasts()
  const [domains, setDomains] = useState<RoutingDomain[]>([])
  const [loading, setLoading] = useState(true)
  const [showNew, setShowNew] = useState(false)

  async function load() {
    setLoading(true)
    try {
      const res = await apiClient.get('/routing-domains', { params: { limit: 1000 } })
      setDomains(res.data.items ?? [])
    } catch (e) { show('error', String(e)) } finally { setLoading(false) }
  }

  useEffect(() => { load() }, []) // eslint-disable-line

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs text-gray-400 uppercase tracking-widest font-medium">Networking</p>
          <h1 className="page-title">Routing Domains</h1>
        </div>
        <button onClick={() => setShowNew(true)} className="btn-primary">+ New Domain</button>
      </div>

      <p className="text-sm text-gray-500">
        A routing domain is a uniqueness scope for IP address assignment. Pools in the same
        domain cannot have overlapping subnets. Configure <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">allowed_prefixes</code> to
        restrict which subnets may be created and to enable the free-CIDR suggestion tool.
      </p>

      {showNew && (
        <NewDomainModal
          onClose={() => setShowNew(false)}
          onSuccess={() => { setShowNew(false); load() }}
        />
      )}

      <div className="tbl-wrap">
        {loading ? (
          <div className="flex items-center justify-center h-40 text-gray-400 text-sm">Loading…</div>
        ) : domains.length === 0 ? (
          <div className="flex items-center justify-center h-40 text-gray-400 text-sm">
            No routing domains configured.
          </div>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>Name</th>
                <th>Description</th>
                <th>Allowed Prefixes</th>
                <th className="text-right">Pools</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {domains.map(d => (
                <tr
                  key={d.id}
                  className="border-b border-border hover:bg-page transition-colors cursor-pointer"
                  onClick={() => navigate(d.id)}
                >
                  <td className="px-4 py-3 font-medium text-sm">{d.name}</td>
                  <td className="px-4 py-3 text-sm text-gray-500">{d.description ?? '—'}</td>
                  <td className="px-4 py-3">
                    {d.allowed_prefixes.length === 0 ? (
                      <span className="text-xs text-gray-400 italic">unrestricted</span>
                    ) : (
                      <div className="flex flex-wrap gap-1">
                        {d.allowed_prefixes.map(p => <PrefixChip key={p} prefix={p} />)}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm text-right tabular-nums text-gray-700">
                    {d.pool_count ?? 0}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <span className="text-xs text-primary">View →</span>
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

// ─── RoutingDomainDetail ──────────────────────────────────────────────────────
function RoutingDomainDetail() {
  const { domain_id } = useParams<{ domain_id: string }>()
  const navigate = useNavigate()
  const { show } = useToasts()
  const [domain, setDomain] = useState<RoutingDomain | null>(null)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(false)

  // Edit form state
  const [editName, setEditName] = useState('')
  const [editDesc, setEditDesc] = useState('')
  const [editPrefixes, setEditPrefixes] = useState<string[]>([])
  const [newPrefix, setNewPrefix] = useState('')
  const [saving, setSaving] = useState(false)

  // Suggest-CIDR state
  const [suggestSize, setSuggestSize] = useState('')
  const [suggesting, setSuggesting] = useState(false)
  const [suggestion, setSuggestion] = useState<SuggestCidrResult | null>(null)
  const [suggestError, setSuggestError] = useState<string | null>(null)

  async function load() {
    if (!domain_id) return
    setLoading(true)
    try {
      const res = await apiClient.get(`/routing-domains/${domain_id}`)
      setDomain(res.data)
    } catch (e) { show('error', String(e)) } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [domain_id]) // eslint-disable-line

  function startEdit() {
    if (!domain) return
    setEditName(domain.name)
    setEditDesc(domain.description ?? '')
    setEditPrefixes([...domain.allowed_prefixes])
    setNewPrefix('')
    setEditing(true)
  }

  function addPrefix() {
    const p = newPrefix.trim()
    if (!p) return
    if (editPrefixes.includes(p)) return
    setEditPrefixes(prev => [...prev, p])
    setNewPrefix('')
  }

  async function saveEdit() {
    if (!domain_id) return
    setSaving(true)
    try {
      await apiClient.patch(`/routing-domains/${domain_id}`, {
        name: editName,
        description: editDesc || null,
        allowed_prefixes: editPrefixes,
      })
      show('success', 'Routing domain updated')
      setEditing(false)
      load()
    } catch (e) { show('error', String(e)) } finally { setSaving(false) }
  }

  async function handleDelete() {
    if (!domain || !domain_id) return
    if (domain.pool_count && domain.pool_count > 0) {
      show('error', `Cannot delete — ${domain.pool_count} pool(s) still reference this domain`)
      return
    }
    if (!confirm(`Delete routing domain "${domain.name}"?`)) return
    try {
      await apiClient.delete(`/routing-domains/${domain_id}`)
      show('success', 'Routing domain deleted')
      navigate('/routing-domains')
    } catch (e: unknown) {
      const data = (e as { response?: { data?: { detail?: string; pool_count?: number } } })?.response?.data
      if (data?.pool_count) {
        show('error', `Cannot delete — ${data.pool_count} pool(s) still reference this domain`)
      } else {
        show('error', String(e))
      }
    }
  }

  async function handleSuggest() {
    if (!domain_id || !suggestSize) return
    const size = parseInt(suggestSize, 10)
    if (isNaN(size) || size < 1) { setSuggestError('Enter a valid number ≥ 1'); return }
    setSuggesting(true)
    setSuggestion(null)
    setSuggestError(null)
    try {
      const res = await apiClient.get(`/routing-domains/${domain_id}/suggest-cidr`, {
        params: { size },
      })
      setSuggestion(res.data)
    } catch (e: unknown) {
      const data = (e as { response?: { data?: { detail?: string; error?: string } } })?.response?.data
      setSuggestError(data?.detail ?? data?.error ?? String(e))
    } finally { setSuggesting(false) }
  }

  if (loading) return <div className="flex items-center justify-center h-60 text-gray-400 text-sm">Loading…</div>
  if (!domain) return null

  return (
    <div className="space-y-4 max-w-3xl">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm">
        <button onClick={() => navigate('/routing-domains')} className="text-primary hover:underline">
          Routing Domains
        </button>
        <span className="text-gray-400">/</span>
        <span className="text-gray-600">{domain.name}</span>
      </div>

      {/* Main card */}
      <div className="card p-6 space-y-5">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">{domain.name}</h2>
            <p className="font-mono text-xs text-gray-400 mt-0.5">{domain.id}</p>
          </div>
          <div className="flex gap-2">
            <button onClick={startEdit} className="btn-ghost text-xs py-1.5 px-3">Edit</button>
            <button onClick={handleDelete} className="btn-danger text-xs py-1.5 px-3"
              title={domain.pool_count ? 'Delete pools first' : 'Delete domain'}>
              Delete
            </button>
          </div>
        </div>

        {!editing ? (
          <div className="grid grid-cols-1 gap-4 text-sm">
            <div>
              <p className="text-xs text-gray-400 uppercase tracking-wide font-medium mb-1">Description</p>
              <p className="text-gray-700">{domain.description ?? <span className="italic text-gray-400">None</span>}</p>
            </div>
            <div>
              <p className="text-xs text-gray-400 uppercase tracking-wide font-medium mb-1">Allowed Prefixes</p>
              {domain.allowed_prefixes.length === 0 ? (
                <p className="text-sm italic text-gray-400">
                  Unrestricted — any subnet is allowed. Add prefixes to restrict and enable CIDR suggestion.
                </p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {domain.allowed_prefixes.map(p => <PrefixChip key={p} prefix={p} />)}
                </div>
              )}
            </div>
            <div>
              <p className="text-xs text-gray-400 uppercase tracking-wide font-medium mb-1">Pools</p>
              <p className="text-gray-700">{domain.pool_count ?? 0} pool{(domain.pool_count ?? 0) !== 1 ? 's' : ''}</p>
            </div>
          </div>
        ) : (
          /* Edit form */
          <div className="space-y-4 border border-primary/30 rounded-lg p-4 bg-primary/5">
            <p className="text-xs font-semibold text-primary uppercase tracking-wide">Editing</p>
            <div className="field">
              <label className="label">Name *</label>
              <input className="input" value={editName} onChange={e => setEditName(e.target.value)} />
            </div>
            <div className="field">
              <label className="label">Description</label>
              <input className="input" placeholder="Optional description" value={editDesc} onChange={e => setEditDesc(e.target.value)} />
            </div>
            <div className="field">
              <label className="label">Allowed Prefixes</label>
              <p className="text-xs text-gray-400 mb-2">
                If set, new pool subnets must be contained within one of these CIDRs.
                Leave empty for unrestricted.
              </p>
              <div className="flex flex-wrap gap-1.5 mb-2">
                {editPrefixes.map(p => (
                  <PrefixChip key={p} prefix={p} onRemove={() => setEditPrefixes(prev => prev.filter(x => x !== p))} />
                ))}
                {editPrefixes.length === 0 && (
                  <span className="text-xs italic text-gray-400">No prefixes — unrestricted</span>
                )}
              </div>
              <div className="flex gap-2">
                <input
                  className="input font-mono text-sm flex-1"
                  placeholder="10.0.0.0/8"
                  value={newPrefix}
                  onChange={e => setNewPrefix(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addPrefix() } }}
                />
                <button onClick={addPrefix} className="btn-ghost text-sm px-3">Add</button>
              </div>
            </div>
            <div className="flex gap-3 pt-2 border-t border-border">
              <button onClick={() => setEditing(false)} className="btn-ghost text-sm">Cancel</button>
              <button onClick={saveEdit} disabled={!editName || saving} className="btn-primary text-sm ml-auto">
                {saving ? 'Saving…' : 'Save Changes'}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Suggest-CIDR tool */}
      <div className="card p-6 space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-gray-800">Free CIDR Suggestion</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            Find the smallest available subnet in this routing domain that provides at
            least the requested number of usable host IPs.
            {domain.allowed_prefixes.length === 0 && (
              <span className="text-amber-600 ml-1">
                ⚠ Requires allowed_prefixes to be configured above.
              </span>
            )}
          </p>
        </div>

        <div className="flex items-end gap-3">
          <div className="field mb-0 flex-1 max-w-xs">
            <label className="label">Minimum usable hosts *</label>
            <input
              className="input font-mono"
              type="number"
              min={1}
              placeholder="e.g. 254"
              value={suggestSize}
              onChange={e => { setSuggestSize(e.target.value); setSuggestion(null); setSuggestError(null) }}
              onKeyDown={e => { if (e.key === 'Enter') handleSuggest() }}
            />
          </div>
          <button
            onClick={handleSuggest}
            disabled={!suggestSize || suggesting || domain.allowed_prefixes.length === 0}
            className="btn-primary"
            title={domain.allowed_prefixes.length === 0 ? 'Configure allowed_prefixes first' : ''}
          >
            {suggesting ? 'Searching…' : 'Suggest CIDR'}
          </button>
        </div>

        {suggestError && (
          <div className="flex gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-xs text-red-700">
            <span className="shrink-0 mt-0.5">✕</span>
            <span>{suggestError}</span>
          </div>
        )}

        {suggestion && (
          <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 space-y-1">
            <p className="text-xs font-semibold text-green-700 uppercase tracking-wide">Suggested CIDR</p>
            <div className="flex items-center gap-3">
              <code className="text-base font-mono font-bold text-green-800">{suggestion.suggested_cidr}</code>
              <span className="text-xs text-green-600">/{suggestion.prefix_len} · {suggestion.usable_hosts.toLocaleString()} usable hosts</span>
              <button
                onClick={() => { navigator.clipboard.writeText(suggestion.suggested_cidr); show('info', 'Copied to clipboard') }}
                className="ml-auto text-xs text-green-600 hover:text-green-800 underline"
              >
                Copy
              </button>
            </div>
            <p className="text-xs text-green-600">
              This CIDR does not overlap any existing pool in routing domain "{suggestion.routing_domain_name}".
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── NewDomainModal ───────────────────────────────────────────────────────────
function NewDomainModal({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [prefixes, setPrefixes] = useState<string[]>([])
  const [newPrefix, setNewPrefix] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function addPrefix() {
    const p = newPrefix.trim()
    if (!p || prefixes.includes(p)) return
    setPrefixes(prev => [...prev, p])
    setNewPrefix('')
  }

  async function handleCreate() {
    setSaving(true)
    setError(null)
    try {
      await apiClient.post('/routing-domains', {
        name,
        description: description || null,
        allowed_prefixes: prefixes,
      })
      onSuccess()
    } catch (e: unknown) {
      const data = (e as { response?: { data?: { detail?: string; error?: string } } })?.response?.data
      if (data?.error === 'domain_name_conflict') {
        setError(`Routing domain "${name}" already exists`)
      } else {
        setError(data?.detail ?? String(e))
      }
    } finally { setSaving(false) }
  }

  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div className="bg-white rounded-xl shadow-2xl w-full max-w-md">
          <div className="flex items-center justify-between px-6 py-4 border-b border-border">
            <h2 className="text-base font-semibold">New Routing Domain</h2>
            <button onClick={onClose} className="btn-icon text-xl leading-none">×</button>
          </div>
          <div className="px-6 py-5 space-y-4">
            <div className="field">
              <label className="label">Name *</label>
              <input
                className="input"
                placeholder="vpn-north"
                value={name}
                onChange={e => setName(e.target.value)}
              />
            </div>
            <div className="field">
              <label className="label">Description (optional)</label>
              <input
                className="input"
                placeholder="North-region VPN pools"
                value={description}
                onChange={e => setDescription(e.target.value)}
              />
            </div>
            <div className="field">
              <label className="label">Allowed Prefixes (optional)</label>
              <p className="text-xs text-gray-400 mb-2">
                Restrict which subnets may be created in this domain. Also enables the free-CIDR
                suggestion tool. Leave empty for unrestricted.
              </p>
              <div className="flex flex-wrap gap-1.5 mb-2">
                {prefixes.map(p => (
                  <PrefixChip key={p} prefix={p} onRemove={() => setPrefixes(prev => prev.filter(x => x !== p))} />
                ))}
                {prefixes.length === 0 && (
                  <span className="text-xs italic text-gray-400">None added — domain will be unrestricted</span>
                )}
              </div>
              <div className="flex gap-2">
                <input
                  className="input font-mono text-sm flex-1"
                  placeholder="10.0.0.0/8"
                  value={newPrefix}
                  onChange={e => setNewPrefix(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addPrefix() } }}
                />
                <button onClick={addPrefix} className="btn-ghost text-sm px-3">Add</button>
              </div>
            </div>

            {error && (
              <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                {error}
              </div>
            )}

            <div className="flex gap-3 pt-2 border-t border-border">
              <button onClick={onClose} className="btn-ghost">Cancel</button>
              <button
                onClick={handleCreate}
                disabled={!name || saving}
                className="btn-primary ml-auto"
              >
                {saving ? 'Creating…' : 'Create Domain'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

// ─── Router ───────────────────────────────────────────────────────────────────
export default function RoutingDomains() {
  return (
    <Routes>
      <Route index element={<RoutingDomainList />} />
      <Route path=":domain_id" element={<RoutingDomainDetail />} />
    </Routes>
  )
}
