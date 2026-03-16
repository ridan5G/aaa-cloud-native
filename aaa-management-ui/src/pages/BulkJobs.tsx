import { useEffect, useRef, useState } from 'react'
import { apiClient } from '../apiClient'
import StatusBadge from '../components/StatusBadge'
import type { BulkJob } from '../types'

function fmtDate(s: string) {
  return new Date(s).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })
}

// ─── Drawer ───────────────────────────────────────────────────────────────────
function JobDrawer({ job, onClose }: { job: BulkJob; onClose: () => void }) {
  const pct = job.submitted > 0 ? Math.round((job.processed / job.submitted) * 100) : 0

  function downloadErrors() {
    if (!job.errors?.length) return
    const header = 'row,field,message,value'
    const rows   = job.errors.map(e => `${e.row},"${e.field}","${e.message}","${e.value}"`)
    const csv    = [header, ...rows].join('\n')
    const blob   = new Blob([csv], { type: 'text/csv' })
    const url    = URL.createObjectURL(blob)
    const a      = Object.assign(document.createElement('a'), {
      href: url, download: `errors-${job.job_id.slice(0, 8)}.csv`,
    })
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />
      <aside className="fixed right-0 top-0 h-full w-full max-w-md bg-white shadow-2xl z-50 flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-border shrink-0">
          <div>
            <p className="text-xs text-gray-400 font-medium uppercase tracking-wide">Job Detail</p>
            <h2 className="text-sm font-semibold font-mono text-gray-900 mt-0.5">{job.job_id}</h2>
          </div>
          <button onClick={onClose} className="btn-icon text-xl leading-none">×</button>
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-5">
          {/* Summary cards */}
          <div className="grid grid-cols-3 gap-3">
            {[
              { label: 'Submitted', value: job.submitted.toLocaleString() },
              { label: 'Processed', value: job.processed.toLocaleString() },
              { label: 'Failed',    value: job.failed.toLocaleString()    },
            ].map(s => (
              <div key={s.label} className="card p-3 text-center">
                <p className="text-xs text-gray-400 uppercase tracking-wide">{s.label}</p>
                <p className={`text-xl font-bold mt-0.5 tabular-nums ${
                  s.label === 'Failed' && job.failed > 0 ? 'text-red-600' : 'text-gray-900'
                }`}>{s.value}</p>
              </div>
            ))}
          </div>

          {/* Progress bar */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <StatusBadge status={job.status} />
              <span className="text-xs text-gray-400 tabular-nums">{pct}%</span>
            </div>
            <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${pct}%`,
                  backgroundColor: job.status === 'failed' ? '#E53E3E' : '#F5A623',
                }}
              />
            </div>
          </div>

          {/* Error table */}
          {(job.errors?.length ?? 0) > 0 && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-semibold text-gray-700">
                  Errors ({job.errors!.length})
                </h3>
                <button onClick={downloadErrors} className="btn-outline text-xs py-1 px-3">
                  ↓ Download CSV
                </button>
              </div>
              <div className="rounded-lg border border-red-200 overflow-hidden">
                <table className="w-full text-xs">
                  <thead className="bg-red-50">
                    <tr>
                      <th className="px-3 py-2 text-left text-red-700 font-semibold w-12">Row</th>
                      <th className="px-3 py-2 text-left text-red-700 font-semibold">Field</th>
                      <th className="px-3 py-2 text-left text-red-700 font-semibold">Message</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-red-100 bg-white">
                    {job.errors!.map((e, i) => (
                      <tr key={i}>
                        <td className="px-3 py-1.5 text-gray-500 tabular-nums">{e.row}</td>
                        <td className="px-3 py-1.5 font-mono text-gray-700">{e.field}</td>
                        <td className="px-3 py-1.5 text-gray-600">{e.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <p className="text-xs text-gray-400">Submitted at {fmtDate(job.created_at)}</p>
        </div>
      </aside>
    </>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────
export default function BulkJobs() {
  const [jobs,     setJobs]     = useState<BulkJob[]>([])
  const [loading,  setLoading]  = useState(true)
  const [error,    setError]    = useState<string | null>(null)
  const [selected, setSelected] = useState<BulkJob | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  async function fetchJobs() {
    try {
      const res = await apiClient.get('/jobs?limit=100')
      setJobs(res.data.jobs ?? res.data.items ?? [])
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchJobs() }, [])

  // Auto-poll while any job is active
  useEffect(() => {
    const hasActive = jobs.some(j => j.status === 'running' || j.status === 'queued')
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
    if (hasActive) timerRef.current = setInterval(fetchJobs, 5000)
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [jobs])

  // Keep drawer in sync while polling
  useEffect(() => {
    if (!selected) return
    const updated = jobs.find(j => j.job_id === selected.job_id)
    if (updated) setSelected(updated)
  }, [jobs]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs text-gray-400 uppercase tracking-widest font-medium">Operations</p>
          <h1 className="page-title">Bulk Jobs</h1>
        </div>
        <button onClick={fetchJobs} className="btn-ghost text-xs flex items-center gap-1">
          ↻ Refresh
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-lg">{error}</div>
      )}

      <div className="tbl-wrap">
        {loading ? (
          <div className="flex items-center justify-center h-40 text-gray-400 text-sm">Loading…</div>
        ) : jobs.length === 0 ? (
          <div className="flex items-center justify-center h-40 text-gray-400 text-sm">No bulk jobs found.</div>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>Job ID</th>
                <th>Submitted</th>
                <th>Status</th>
                <th className="text-right">Processed</th>
                <th className="text-right">Failed</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {jobs.map(j => (
                <tr
                  key={j.job_id}
                  className="border-b border-border hover:bg-page transition-colors cursor-pointer"
                  onClick={() => setSelected(j)}
                >
                  <td className="px-4 py-3 font-mono text-xs text-gray-500">{j.job_id.slice(0, 12)}…</td>
                  <td className="px-4 py-3 text-sm text-gray-500 whitespace-nowrap">{fmtDate(j.created_at)}</td>
                  <td className="px-4 py-3"><StatusBadge status={j.status} /></td>
                  <td className="px-4 py-3 text-sm text-right tabular-nums">{j.processed.toLocaleString()}</td>
                  <td className="px-4 py-3 text-sm text-right tabular-nums">
                    <span className={j.failed > 0 ? 'text-red-600 font-medium' : 'text-gray-500'}>
                      {j.failed.toLocaleString()}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      className="text-xs text-primary hover:underline"
                      onClick={e => { e.stopPropagation(); setSelected(j) }}
                    >
                      Details →
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {selected && <JobDrawer job={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}
