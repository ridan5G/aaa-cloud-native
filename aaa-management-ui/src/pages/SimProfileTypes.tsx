import { Link } from 'react-router-dom'
import type { IpResolution } from '../types'
import { ImsiDiagram, ImsiApnDiagram, IccidDiagram, IccidApnDiagram } from '../components/SimProfileDiagram'

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
    storage:     'sim_apn_ips  (apn = NULL)',
    description: 'The physical SIM card (ICCID) gets one IP address, shared across all IMSIs loaded onto it. First-connection auto-provisions all sibling IMSIs.',
    useCases:    ['Multi-IMSI SIM roaming profiles', 'Dual-SIM hotspot cards', 'Carrier aggregation scenarios'],
    Diagram:     IccidDiagram,
  },
  {
    key:         'iccid_apn',
    title:       'ICCID + APN',
    subtitle:    'Card-level, per-APN',
    accentColor: 'border-green-400',
    storage:     'sim_apn_ips  (apn = <value>)',
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
          to={`/devices/new`}
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

// ─── Page ─────────────────────────────────────────────────────────────────────
export default function SimProfileTypes() {
  return (
    <div className="space-y-6 max-w-6xl">
      <div>
        <p className="text-xs text-gray-400 uppercase tracking-widest font-medium">Reference</p>
        <h1 className="page-title">SIM Profile Types</h1>
        <p className="text-sm text-gray-500 mt-1 max-w-2xl">
          Each SIM profile has an <code className="bg-gray-100 px-1.5 py-0.5 rounded text-xs">ip_resolution</code> mode that
          determines how IP addresses are allocated — per IMSI, per APN, or at the physical card (ICCID) level.
        </p>
      </div>

      {/* 4 type cards */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {PROFILE_TYPES.map(def => <ProfileTypeCard key={def.key} def={def} />)}
      </div>
    </div>
  )
}
