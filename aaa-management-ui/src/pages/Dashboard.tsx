import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiClient } from '../apiClient'
import StatusBadge from '../components/StatusBadge'
import type { BulkJob } from '../types'

interface PoolStat { pool_id: string; name: string; total: number; allocated: number; available: number }

function poolBarColor(pct: number) {
  if (pct > 90) return '#E53E3E'
  if (pct > 75) return '#E07B39'
  return '#F5A623'
}

function StatCard({ label, value, sub, icon }: { label: string; value: string; sub?: string; icon: React.ReactNode }) {
  return (
    <div className="card p-5 flex items-start gap-4">
      <div className="w-10 h-10 rounded-full bg-primary/10 text-primary flex items-center justify-center shrink-0">
        {icon}
      </div>
      <div>
        <p className="text-xs text-gray-500 uppercase tracking-wide font-medium">{label}</p>
        <p className="text-2xl font-bold text-gray-900 mt-0.5 tabular-nums">{value}</p>
        {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
      </div>
    </div>
  )
}

export default function Dashboard() {
  const [activeSims, setActiveSims] = useState<number | null>(null)
  const [pools, setPools]           = useState<PoolStat[]>([])
  const [jobs, setJobs]             = useState<BulkJob[]>([])
  const [error, setError]           = useState<string | null>(null)

  useEffect(() => {
    Promise.all([
      apiClient.get('/profiles?status=active&limit=1').catch(() => null),
      apiClient.get('/pools').catch(() => null),
      apiClient.get('/jobs?limit=5').catch(() => null),
    ]).then(([pr, poolsR, jobsR]) => {
      if (pr)     setActiveSims(pr.data.total ?? 0)
      if (poolsR) setPools(poolsR.data.pools ?? poolsR.data.items ?? [])
      if (jobsR)  setJobs(jobsR.data.jobs   ?? jobsR.data.items  ?? [])
    }).catch(e => setError(String(e)))
  }, [])

  const running = jobs.filter(j => j.status === 'running' || j.status === 'queued').length
  const failed  = jobs.filter(j => j.status === 'failed').length

  return (
    <div className="space-y-6 max-w-6xl">
      <div>
        <p className="text-xs text-gray-400 uppercase tracking-widest font-medium mb-1">Overview</p>
        <h1 className="page-title">Dashboard</h1>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-lg">
          {error}
        </div>
      )}

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Active SIMs"
          value={activeSims !== null ? activeSims.toLocaleString() : '—'}
          icon={<SimIcon />}
        />
        <StatCard
          label="IP Pools"
          value={pools.length.toString()}
          icon={<PoolIcon />}
        />
        <StatCard
          label="Running Jobs"
          value={running.toString()}
          icon={<JobIcon />}
        />
        <StatCard
          label="Failed Jobs"
          value={failed.toString()}
          sub="in recent 5"
          icon={<WarnIcon />}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Pool utilization */}
        <div className="card p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-gray-900">Pool Utilization</h2>
            <Link to="/pools" className="text-xs text-primary hover:underline">View all →</Link>
          </div>
          {pools.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-8">No pools configured.</p>
          ) : (
            <div className="space-y-4">
              {pools.map(p => {
                const pct = p.total > 0 ? Math.round((p.allocated / p.total) * 100) : 0
                return (
                  <div key={p.pool_id}>
                    <div className="flex justify-between text-xs mb-1.5">
                      <span className="font-medium text-gray-700 truncate max-w-[160px]">{p.name}</span>
                      <span className="text-gray-500 shrink-0 ml-2 tabular-nums">
                        {(p.allocated ?? 0).toLocaleString()} / {(p.total ?? 0).toLocaleString()} ({pct}%)
                      </span>
                    </div>
                    <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all duration-300"
                        style={{ width: `${pct}%`, backgroundColor: poolBarColor(pct) }}
                      />
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Recent bulk jobs */}
        <div className="card p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-gray-900">Recent Bulk Jobs</h2>
            <Link to="/bulk-jobs" className="text-xs text-primary hover:underline">View all →</Link>
          </div>
          {jobs.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-8">No recent jobs.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-xs text-gray-500 uppercase tracking-wide">
                  <th className="pb-2 text-left font-semibold">Job ID</th>
                  <th className="pb-2 text-left font-semibold">Status</th>
                  <th className="pb-2 text-right font-semibold">Processed</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {jobs.map(j => (
                  <tr key={j.job_id} className="hover:bg-page">
                    <td className="py-2.5 font-mono text-xs text-gray-500">{j.job_id.slice(0, 8)}…</td>
                    <td className="py-2.5"><StatusBadge status={j.status} /></td>
                    <td className="py-2.5 text-right tabular-nums text-gray-600">
                      {(j.processed ?? 0).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Quick actions */}
      <div>
        <h2 className="text-sm font-semibold text-gray-700 mb-3">Quick Actions</h2>
        <div className="flex flex-wrap gap-3">
          <Link to="/devices/new"           className="btn-primary">+ New Profile</Link>
          <Link to="/devices/bulk"          className="btn-outline">↑ Bulk Import</Link>
          <Link to="/pools?new=1"          className="btn-outline">+ New Pool</Link>
          <Link to="/iccid-range-configs?new=1" className="btn-outline">+ ICCID Range Config</Link>
        </div>
      </div>
    </div>
  )
}

// Local inline icons
function SimIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="w-5 h-5">
      <rect x="3" y="1" width="10" height="14" rx="2" />
      <path d="M6 1v3h4V1" fill="currentColor" stroke="none" />
      <rect x="5" y="6" width="6" height="5" rx="1" />
    </svg>
  )
}
function PoolIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" className="w-5 h-5">
      <path d="M8 2.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zm0 1.5a4 4 0 110 8 4 4 0 010-8z" />
      <circle cx="8" cy="8" r="2" />
    </svg>
  )
}
function JobIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" className="w-5 h-5">
      <rect x="1" y="1.5"  width="14" height="2.5" rx="1.25" />
      <rect x="1" y="6.75" width="14" height="2.5" rx="1.25" />
      <rect x="1" y="12"   width="14" height="2.5" rx="1.25" />
    </svg>
  )
}
function WarnIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" className="w-5 h-5">
      <path d="M8 1.5L1 14h14L8 1.5zm0 3l4 7.5H4L8 4.5z" />
      <rect x="7.25" y="7.5" width="1.5" height="3" rx="0.75" />
      <circle cx="8" cy="11.5" r="0.75" />
    </svg>
  )
}
