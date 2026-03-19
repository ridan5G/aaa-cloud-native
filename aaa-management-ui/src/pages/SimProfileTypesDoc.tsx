// ─── Documentation: Quick Comparison + Data Model + First-Connection Flow ────

function Arrow() { return <div className="flex items-center gap-1 text-gray-400 text-xs font-mono px-1">→</div> }

// ─── Comparison Table ─────────────────────────────────────────────────────────
function ComparisonTable() {
  const rows = [
    { label: 'IP stored at',             imsi: 'IMSI level',   imsi_apn: 'IMSI level',   iccid: 'Card (ICCID)',  iccid_apn: 'Card (ICCID)' },
    { label: 'APN-aware',                imsi: '✗',            imsi_apn: '✓',            iccid: '✗',            iccid_apn: '✓' },
    { label: 'IMSIs share IP',           imsi: '✗',            imsi_apn: '✗',            iccid: '✓',            iccid_apn: '✓ per APN' },
    { label: 'DB table',                 imsi: 'imsi_apn_ips', imsi_apn: 'imsi_apn_ips', iccid: 'sim_apn_ips',  iccid_apn: 'sim_apn_ips' },
    { label: 'Auto-sibling provisioning',imsi: '—',            imsi_apn: '—',            iccid: '✓',            iccid_apn: '✓' },
  ]
  return (
    <div className="tbl-wrap">
      <table className="tbl">
        <thead>
          <tr>
            <th className="w-40">Attribute</th>
            <th className="text-center">imsi</th>
            <th className="text-center">imsi_apn</th>
            <th className="text-center">iccid</th>
            <th className="text-center">iccid_apn</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.label} className="border-b border-border">
              <td className="px-4 py-2.5 text-xs font-medium text-gray-700">{r.label}</td>
              <td className="px-4 py-2.5 text-center font-mono text-xs text-gray-600">{r.imsi}</td>
              <td className="px-4 py-2.5 text-center font-mono text-xs text-gray-600">{r.imsi_apn}</td>
              <td className="px-4 py-2.5 text-center font-mono text-xs text-gray-600">{r.iccid}</td>
              <td className="px-4 py-2.5 text-center font-mono text-xs text-gray-600">{r.iccid_apn}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─── DB Schema Visualization ──────────────────────────────────────────────────
type TableAccent = 'navy' | 'blue' | 'green' | 'amber' | 'purple'

const TABLE_ACCENT: Record<TableAccent, string> = {
  navy:   'border-t-[#1C2340] bg-[#1C2340]/5',
  blue:   'border-t-blue-400 bg-blue-50/50',
  green:  'border-t-green-400 bg-green-50/50',
  amber:  'border-t-amber-400 bg-amber-50/50',
  purple: 'border-t-purple-400 bg-purple-50/50',
}

function DbTable({ name, fields, accent }: { name: string; fields: string[]; accent: TableAccent }) {
  return (
    <div className={`border border-border rounded-lg overflow-hidden border-t-2 ${TABLE_ACCENT[accent]} min-w-[180px]`}>
      <div className="px-3 py-2 border-b border-border">
        <p className="text-xs font-semibold text-gray-800 font-mono">{name}</p>
      </div>
      <div className="px-3 py-2 space-y-0.5">
        {fields.map(f => (
          <p key={f} className="text-[10px] font-mono text-gray-500">{f}</p>
        ))}
      </div>
    </div>
  )
}

function DbSchemaVisualization() {
  return (
    <div className="card p-6 space-y-6">
      <div>
        <h3 className="text-sm font-semibold text-gray-900 mb-1">Data Model</h3>
        <p className="text-xs text-gray-500">How SIM data is stored across database tables</p>
      </div>

      {/* Core tables */}
      <div className="space-y-4">
        <p className="text-xs text-gray-400 uppercase tracking-wide font-medium">Profile Data Flow</p>
        <div className="overflow-x-auto pb-2">
          <div className="flex items-center gap-2 min-w-max">
            <DbTable name="sim_profiles" fields={['sim_id (PK)', 'iccid', 'account_name', 'status', 'ip_resolution', 'metadata']} accent="navy" />
            <div className="flex flex-col gap-6 items-start">
              <div className="flex items-center gap-2">
                <Arrow />
                <DbTable name="imsi2sim" fields={['imsi (PK)', 'sim_id (FK)', 'priority', 'status']} accent="blue" />
                <Arrow />
                <DbTable name="imsi_apn_ips" fields={['imsi (FK)', 'apn (nullable)', 'static_ip', 'pool_id (FK)']} accent="green" />
              </div>
              <div className="flex items-center gap-2">
                <Arrow />
                <DbTable name="sim_apn_ips" fields={['sim_id (FK)', 'apn (nullable)', 'static_ip', 'pool_id (FK)']} accent="purple" />
              </div>
            </div>
          </div>
          <p className="text-xs text-gray-400 mt-2 ml-2 italic">
            imsi_apn_ips used for <code className="bg-gray-100 px-1 rounded">imsi / imsi_apn</code> modes ·
            sim_apn_ips used for <code className="bg-gray-100 px-1 rounded">iccid / iccid_apn</code> modes
          </p>
        </div>

        {/* Range config tables */}
        <p className="text-xs text-gray-400 uppercase tracking-wide font-medium mt-4">Range Config Hierarchy</p>
        <div className="overflow-x-auto pb-2">
          <div className="flex items-center gap-2 min-w-max">
            <DbTable name="iccid_range_configs" fields={['id (PK)', 'f_iccid / t_iccid', 'imsi_count', 'pool_id', 'ip_resolution']} accent="navy" />
            <Arrow />
            <DbTable name="imsi_range_configs" fields={['id (PK)', 'iccid_range_id (FK, nullable)', 'f_imsi / t_imsi', 'imsi_slot', 'pool_id']} accent="blue" />
            <Arrow />
            <DbTable name="range_config_apn_pools" fields={['id (PK)', 'range_config_id (FK)', 'apn', 'pool_id (FK)']} accent="amber" />
          </div>
          <p className="text-xs text-gray-400 mt-2 ml-2 italic">
            imsi_range_configs with <code className="bg-gray-100 px-1 rounded">iccid_range_id = NULL</code> are standalone IMSI ranges
          </p>
        </div>

        {/* Pools */}
        <p className="text-xs text-gray-400 uppercase tracking-wide font-medium mt-4">IP Pool Tables</p>
        <div className="overflow-x-auto pb-2">
          <div className="flex items-center gap-2 min-w-max">
            <DbTable name="ip_pools" fields={['pool_id (PK)', 'name', 'subnet', 'start_ip / end_ip', 'status']} accent="green" />
            <Arrow />
            <DbTable name="ip_pool_available" fields={['pool_id (FK)', 'ip_address', 'allocated (bool)']} accent="blue" />
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── First-Connection Flow ────────────────────────────────────────────────────
function FirstConnectionFlow() {
  const steps = [
    { n: '1', label: 'AAA RADIUS receives Access-Request', sub: 'IMSI + APN from network' },
    { n: '2', label: 'POST /first-connection', sub: '{ imsi, apn, imei }' },
    { n: '3', label: 'Lookup imsi_range_configs', sub: 'Match IMSI within f_imsi…t_imsi range' },
    { n: '4', label: 'Resolve pool', sub: 'APN override → slot pool → parent pool' },
    { n: '5', label: 'Allocate IP + create profile', sub: 'Also pre-provisions all sibling IMSIs' },
    { n: '6', label: 'Return static_ip', sub: '201 new · 200 idempotent (existing)' },
  ]
  return (
    <div className="card p-6 space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-gray-900 mb-1">First-Connection Auto-Provisioning</h3>
        <p className="text-xs text-gray-500">How a new SIM is provisioned automatically on first network attach</p>
      </div>
      <div className="flex flex-col gap-0">
        {steps.map((s, i) => (
          <div key={s.n} className="flex items-start gap-3">
            <div className="flex flex-col items-center">
              <div className="w-7 h-7 rounded-full bg-primary/10 text-primary flex items-center justify-center text-xs font-bold shrink-0">
                {s.n}
              </div>
              {i < steps.length - 1 && <div className="w-px h-6 bg-gray-200" />}
            </div>
            <div className="pt-1 pb-4">
              <p className="text-sm font-medium text-gray-800">{s.label}</p>
              <p className="text-xs text-gray-500 font-mono mt-0.5">{s.sub}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────
export default function SimProfileTypesDoc() {
  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs text-gray-400 uppercase tracking-widest font-medium">Reference</p>
        <h1 className="page-title">Documentation</h1>
        <p className="text-sm text-gray-500 mt-1 max-w-2xl">
          Technical reference for SIM profile types, database schema, and the first-connection auto-provisioning flow.
        </p>
      </div>

      {/* Quick Comparison */}
      <div className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-700">Quick Comparison of SIM Types</h2>
        <ComparisonTable />
      </div>

      {/* Data Model — full page width */}
      <DbSchemaVisualization />

      {/* First-Connection Auto-Provisioning */}
      <FirstConnectionFlow />
    </div>
  )
}
