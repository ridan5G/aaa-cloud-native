import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiClient } from '../apiClient'

interface PoolSummary {
  pool_id: string
  name: string
  total: number
  allocated: number
}

interface BulkJob {
  job_id: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  submitted: number
  processed: number
  created_at: string
}

const statusColor: Record<string, string> = {
  queued:    'bg-gray-200 text-gray-700',
  running:   'bg-blue-100 text-blue-700',
  completed: 'bg-green-100 text-green-700',
  failed:    'bg-red-100 text-red-700',
}

export default function Dashboard() {
  const [activeSims, setActiveSims]   = useState<number | null>(null)
  const [pools, setPools]             = useState<PoolSummary[]>([])
  const [jobs, setJobs]               = useState<BulkJob[]>([])
  const [error, setError]             = useState<string | null>(null)

  useEffect(() => {
    Promise.all([
      apiClient.get('/profiles?status=active&limit=1').catch(() => null),
      apiClient.get('/pools').catch(() => null),
      apiClient.get('/jobs?limit=5').catch(() => null),
    ]).then(([profilesRes, poolsRes, jobsRes]) => {
      if (profilesRes) setActiveSims(profilesRes.data.total ?? 0)
      if (poolsRes)    setPools(poolsRes.data.pools ?? [])
      if (jobsRes)     setJobs(jobsRes.data.jobs ?? [])
    }).catch(err => setError(String(err)))
  }, [])

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-semibold">Dashboard</h1>

      {error && (
        <div className="rounded bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Quick stats */}
      <div className="grid grid-cols-3 gap-4">
        <StatCard
          label="Active SIMs"
          value={activeSims !== null ? activeSims.toLocaleString() : '—'}
        />
        <StatCard label="IP Pools" value={pools.length.toString()} />
        <StatCard
          label="Running Jobs"
          value={jobs.filter(j => j.status === 'running').length.toString()}
        />
      </div>

      {/* Pool utilization */}
      <section>
        <h2 className="text-base font-medium mb-3">Pool Utilization</h2>
        {pools.length === 0 ? (
          <p className="text-sm text-gray-500">No pools found.</p>
        ) : (
          <div className="space-y-3">
            {pools.map(p => {
              const pct = p.total > 0 ? Math.round((p.allocated / p.total) * 100) : 0
              return (
                <div key={p.pool_id} className="bg-white rounded border border-gray-200 px-4 py-3">
                  <div className="flex justify-between text-sm mb-1">
                    <span className="font-medium">{p.name}</span>
                    <span className="text-gray-500">{p.allocated} / {p.total} ({pct}%)</span>
                  </div>
                  <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-indigo-500 rounded-full"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </section>

      {/* Recent bulk jobs */}
      <section>
        <h2 className="text-base font-medium mb-3">Recent Bulk Jobs</h2>
        {jobs.length === 0 ? (
          <p className="text-sm text-gray-500">No recent jobs.</p>
        ) : (
          <table className="w-full text-sm border border-gray-200 rounded overflow-hidden">
            <thead className="bg-gray-50 text-gray-600">
              <tr>
                <th className="px-4 py-2 text-left font-medium">Job ID</th>
                <th className="px-4 py-2 text-left font-medium">Status</th>
                <th className="px-4 py-2 text-right font-medium">Processed</th>
                <th className="px-4 py-2 text-left font-medium">Submitted</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {jobs.map(j => (
                <tr key={j.job_id}>
                  <td className="px-4 py-2 font-mono text-xs">{j.job_id.slice(0, 8)}…</td>
                  <td className="px-4 py-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusColor[j.status] ?? ''}`}>
                      {j.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-right">{j.processed}</td>
                  <td className="px-4 py-2 text-gray-500">{new Date(j.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* Quick links */}
      <div className="flex gap-3">
        <Link to="/subscribers?new=1" className="px-4 py-2 bg-indigo-600 text-white text-sm rounded hover:bg-indigo-700">
          + New Profile
        </Link>
        <Link to="/subscribers/bulk" className="px-4 py-2 bg-white border border-gray-300 text-sm rounded hover:bg-gray-50">
          Bulk Import
        </Link>
        <Link to="/pools?new=1" className="px-4 py-2 bg-white border border-gray-300 text-sm rounded hover:bg-gray-50">
          + New Pool
        </Link>
      </div>
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white rounded border border-gray-200 px-5 py-4">
      <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">{label}</div>
      <div className="text-2xl font-semibold">{value}</div>
    </div>
  )
}
