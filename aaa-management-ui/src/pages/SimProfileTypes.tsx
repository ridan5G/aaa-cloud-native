import { Link } from 'react-router-dom'
import type { IpResolution } from '../types'

// ─── Diagram Primitives ───────────────────────────────────────────────────────
type NodeColor = 'navy' | 'blue' | 'amber' | 'green' | 'purple'

const NODE_STYLE: Record<NodeColor, string> = {
  navy:   'bg-[#1C2340] text-white border-[#1C2340]',
  blue:   'bg-blue-50 text-blue-700 border-blue-300',
  amber:  'bg-amber-50 text-amber-700 border-amber-300',
  green:  'bg-green-50 text-green-700 border-green-300',
  purple: 'bg-purple-50 text-purple-700 border-purple-300',
}

function Node({ color, label, sub, wide }: { color: NodeColor; label: string; sub?: string; wide?: boolean }) {
  return (
    <div className={`border rounded-lg text-center px-3 py-1.5 ${wide ? 'min-w-[110px]' : 'min-w-[80px]'} ${NODE_STYLE[color]}`}>
      <div className="text-xs font-semibold">{label}</div>
      {sub && <div className="font-mono text-[10px] opacity-80 mt-0.5">{sub}</div>}
    </div>
  )
}

function VLine() { return <div className="w-px h-3 bg-gray-300 mx-auto" /> }
function Arrow() { return <div className="flex items-center gap-1 text-gray-400 text-xs font-mono px-1">→</div> }

// ─── Diagram: IMSI Mode ───────────────────────────────────────────────────────
function ImsiDiagram() {
  return (
    <div className="flex flex-col items-center py-2 select-none">
      <Node color="navy" label="SIM Card" />
      <VLine />
      {/* Horizontal bridge */}
      <div className="flex items-start">
        <div className="flex flex-col items-center">
          <div className="w-16 h-px bg-gray-300" />
        </div>
        <div className="flex gap-4">
          <div className="flex flex-col items-center gap-0">
            <div className="w-px h-3 bg-gray-300" />
            <Node color="blue" label="IMSI-1" sub="278…001" />
            <VLine />
            <Node color="green" label="IP" sub="100.65.0.1" />
          </div>
          <div className="flex flex-col items-center gap-0">
            <div className="w-px h-3 bg-gray-300" />
            <Node color="blue" label="IMSI-2" sub="278…002" />
            <VLine />
            <Node color="green" label="IP" sub="100.65.0.2" />
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Diagram: IMSI + APN Mode ─────────────────────────────────────────────────
function ImsiApnDiagram() {
  return (
    <div className="flex flex-col items-center py-2 select-none">
      <Node color="navy" label="SIM Card" />
      <VLine />
      <Node color="blue" label="IMSI-1" sub="278…001" />
      <VLine />
      <div className="flex gap-3">
        <div className="flex flex-col items-center gap-0">
          <div className="w-px h-3 bg-gray-300" />
          <Node color="amber" label="APN-A" sub="internet" />
          <VLine />
          <Node color="green" label="IP" sub="100.65.0.1" />
        </div>
        <div className="flex flex-col items-center gap-0">
          <div className="w-px h-3 bg-gray-300" />
          <Node color="amber" label="APN-B" sub="ims" />
          <VLine />
          <Node color="green" label="IP" sub="100.65.0.2" />
        </div>
      </div>
      <div className="mt-1.5 text-[10px] text-gray-400 italic">Each IMSI × APN pair = dedicated IP</div>
    </div>
  )
}

// ─── Diagram: ICCID Mode ─────────────────────────────────────────────────────
function IccidDiagram() {
  return (
    <div className="flex flex-col items-center py-2 select-none">
      <Node color="navy" label="SIM Card" sub="ICCID-level" wide />
      <VLine />
      {/* Shared IP is at the card (ICCID) level — connected directly to SIM Card */}
      <Node color="green" label="Shared IP" sub="100.65.0.1" wide />
      <VLine />
      {/* All IMSIs on the card branch down from the shared IP */}
      <div className="flex gap-3">
        <div className="flex flex-col items-center gap-0">
          <div className="w-px h-3 bg-gray-300" />
          <Node color="blue" label="IMSI-1" sub="278…001" />
        </div>
        <div className="flex flex-col items-center gap-0">
          <div className="w-px h-3 bg-gray-300" />
          <Node color="blue" label="IMSI-2" sub="278…002" />
        </div>
        <div className="flex flex-col items-center gap-0">
          <div className="w-px h-3 bg-gray-300" />
          <Node color="blue" label="IMSI-3" sub="278…003" />
        </div>
      </div>
      <div className="mt-1.5 text-[10px] text-gray-400 italic">All IMSIs on the card share one IP</div>
    </div>
  )
}

// ─── Diagram: ICCID + APN Mode ───────────────────────────────────────────────
function IccidApnDiagram() {
  return (
    <div className="flex flex-col items-center py-2 select-none">
      <Node color="navy" label="SIM Card" sub="ICCID-level" wide />
      <VLine />
      {/* APNs connect directly to SIM Card (not through individual IMSIs) */}
      <div className="flex gap-3">
        <div className="flex flex-col items-center gap-0">
          <div className="w-px h-3 bg-gray-300" />
          <Node color="amber" label="APN-A" sub="internet" />
          <VLine />
          {/* IP remains connected to the APN */}
          <Node color="green" label="Shared IP" sub="100.65.0.1" wide />
        </div>
        <div className="flex flex-col items-center gap-0">
          <div className="w-px h-3 bg-gray-300" />
          <Node color="amber" label="APN-B" sub="ims" />
          <VLine />
          {/* IP remains connected to the APN */}
          <Node color="green" label="Shared IP" sub="100.65.0.2" wide />
        </div>
      </div>
      <div className="mt-1.5 text-[10px] text-gray-400 italic">All IMSIs share card-level IPs per APN</div>
    </div>
  )
}

// ─── Profile Type Card ────────────────────────────────────────────────────────
interface ProfileTypeDef {
  key:         IpResolution
  title:       string
  subtitle:    string
  accentColor: string
  storage:     string
  description: string
  useCases:    string[]
  Diagram:     React.ComponentType
}

const PROFILE_TYPES: ProfileTypeDef[] = [
  {
    key:         'imsi',
    title:       'IMSI',
    subtitle:    'Per-IMSI, APN-agnostic',
    accentColor: 'border-blue-400',
    storage:     'imsi_apn_ips  (apn = NULL)',
    description: 'Each IMSI on the SIM card receives its own dedicated IP address from the pool, regardless of which APN is used for the connection.',
    useCases:    ['Single-SIM IoT devices', 'Fixed-IP data-only subscriptions', 'Low-complexity CGNAT setups'],
    Diagram:     ImsiDiagram,
  },
  {
    key:         'imsi_apn',
    title:       'IMSI + APN',
    subtitle:    'Per-IMSI, per-APN',
    accentColor: 'border-amber-400',
    storage:     'imsi_apn_ips  (apn = <value>)',
    description: 'Each IMSI gets a separate IP per APN. Enables traffic steering — data goes through one pool, IMS voice through another.',
    useCases:    ['IMS/VoLTE voice + data split', 'Per-service IP policies', 'Multi-service M2M devices'],
    Diagram:     ImsiApnDiagram,
  },
  {
    key:         'iccid',
    title:       'ICCID',
    subtitle:    'Card-level, APN-agnostic',
    accentColor: 'border-purple-400',
    storage:     'device_apn_ips  (apn = NULL)',
    description: 'The physical SIM card (ICCID) gets one IP address, shared across all IMSIs loaded onto it. First-connection auto-provisions all sibling IMSIs.',
    useCases:    ['Multi-IMSI SIM roaming profiles', 'Dual-SIM hotspot cards', 'Carrier aggregation scenarios'],
    Diagram:     IccidDiagram,
  },
  {
    key:         'iccid_apn',
    title:       'ICCID + APN',
    subtitle:    'Card-level, per-APN',
    accentColor: 'border-green-400',
    storage:     'device_apn_ips  (apn = <value>)',
    description: 'The physical SIM card shares IPs per APN across all its IMSIs. Combines card-level sharing with per-service traffic steering.',
    useCases:    ['Multi-IMSI SIM with VoLTE', 'Roaming profiles with IMS split', 'Complex multi-profile IoT cards'],
    Diagram:     IccidApnDiagram,
  },
]

function ProfileTypeCard({ def }: { def: ProfileTypeDef }) {
  const { Diagram } = def
  return (
    <div className={`card p-5 flex flex-col gap-4 border-l-4 ${def.accentColor}`}>
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-base font-semibold text-gray-900">{def.title}</h3>
          <p className="text-xs text-gray-500 mt-0.5">{def.subtitle}</p>
        </div>
        <Link
          to={`/subscribers/new`}
          className="btn-outline text-xs py-1 px-2.5 shrink-0">
          Create →
        </Link>
      </div>

      {/* Diagram */}
      <div className="bg-gray-50 rounded-lg p-3 flex items-center justify-center min-h-[150px]">
        <Diagram />
      </div>

      {/* Description */}
      <p className="text-sm text-gray-600 leading-relaxed">{def.description}</p>

      {/* Storage label */}
      <div>
        <p className="text-xs text-gray-400 uppercase tracking-wide font-medium mb-1">DB Storage</p>
        <code className="text-xs bg-gray-100 text-gray-700 px-2 py-1 rounded font-mono">{def.storage}</code>
      </div>

      {/* Use cases */}
      <div>
        <p className="text-xs text-gray-400 uppercase tracking-wide font-medium mb-1">Use Cases</p>
        <ul className="space-y-1">
          {def.useCases.map(u => (
            <li key={u} className="flex items-start gap-1.5 text-xs text-gray-600">
              <span className="text-primary mt-0.5 shrink-0">•</span>
              {u}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

// ─── Comparison Table ─────────────────────────────────────────────────────────
function ComparisonTable() {
  const rows = [
    { label: 'IP stored at', imsi: 'IMSI level', imsi_apn: 'IMSI level', iccid: 'Card (ICCID)', iccid_apn: 'Card (ICCID)' },
    { label: 'APN-aware', imsi: '✗', imsi_apn: '✓', iccid: '✗', iccid_apn: '✓' },
    { label: 'IMSIs share IP', imsi: '✗', imsi_apn: '✗', iccid: '✓', iccid_apn: '✓ per APN' },
    { label: 'DB table', imsi: 'imsi_apn_ips', imsi_apn: 'imsi_apn_ips', iccid: 'device_apn_ips', iccid_apn: 'device_apn_ips' },
    { label: 'Auto-sibling provisioning', imsi: '—', imsi_apn: '—', iccid: '✓', iccid_apn: '✓' },
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
function DbSchemaVisualization() {
  return (
    <div className="card p-6 space-y-6">
      <div>
        <h3 className="text-sm font-semibold text-gray-900 mb-1">Data Model</h3>
        <p className="text-xs text-gray-500">How subscriber data is stored across database tables</p>
      </div>

      {/* Core tables */}
      <div className="space-y-4">
        <p className="text-xs text-gray-400 uppercase tracking-wide font-medium">Profile Data Flow</p>
        <div className="overflow-x-auto pb-2">
          <div className="flex items-center gap-2 min-w-max">
            <DbTable name="device_profiles" fields={['device_id (PK)', 'iccid', 'account_name', 'status', 'ip_resolution', 'metadata']} accent="navy" />
            <div className="flex flex-col gap-6 items-start">
              <div className="flex items-center gap-2">
                <Arrow />
                <DbTable name="imsi2device" fields={['imsi (PK)', 'device_id (FK)', 'priority', 'status']} accent="blue" />
                <Arrow />
                <DbTable name="imsi_apn_ips" fields={['imsi (FK)', 'apn (nullable)', 'static_ip', 'pool_id (FK)']} accent="green" />
              </div>
              <div className="flex items-center gap-2">
                <Arrow />
                <DbTable name="device_apn_ips" fields={['device_id (FK)', 'apn (nullable)', 'static_ip', 'pool_id (FK)']} accent="purple" />
              </div>
            </div>
          </div>
          <p className="text-xs text-gray-400 mt-2 ml-2 italic">
            imsi_apn_ips used for <code className="bg-gray-100 px-1 rounded">imsi / imsi_apn</code> modes ·
            device_apn_ips used for <code className="bg-gray-100 px-1 rounded">iccid / iccid_apn</code> modes
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
export default function SimProfileTypes() {
  return (
    <div className="space-y-6 max-w-6xl">
      <div>
        <p className="text-xs text-gray-400 uppercase tracking-widest font-medium">Reference</p>
        <h1 className="page-title">SIM Profile Types</h1>
        <p className="text-sm text-gray-500 mt-1 max-w-2xl">
          Each subscriber profile has an <code className="bg-gray-100 px-1.5 py-0.5 rounded text-xs">ip_resolution</code> mode that
          determines how IP addresses are allocated — per IMSI, per APN, or at the physical card (ICCID) level.
        </p>
      </div>

      {/* 4 type cards */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {PROFILE_TYPES.map(def => <ProfileTypeCard key={def.key} def={def} />)}
      </div>

      {/* Comparison table */}
      <div className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-700">Quick Comparison</h2>
        <ComparisonTable />
      </div>

      {/* DB schema + first-connection flow */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <FirstConnectionFlow />
        <DbSchemaVisualization />
      </div>
    </div>
  )
}
