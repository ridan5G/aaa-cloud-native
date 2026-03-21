import type { IpResolution, Imsi, IccidIp } from '../types'

// ─── Real-data bag (all fields optional — omit for placeholder mode) ───────────
export interface DiagramData {
  iccid?:    string | null
  imsis?:    Imsi[]
  iccidIps?: IccidIp[]
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function trunc(s: string | null | undefined, head = 6, tail = 3): string {
  if (!s) return '—'
  if (s.length <= head + tail + 1) return s
  return `${s.slice(0, head)}…${s.slice(-tail)}`
}

// ─── Primitives ───────────────────────────────────────────────────────────────
type NodeColor = 'navy' | 'blue' | 'amber' | 'green' | 'purple'

const NODE_STYLE: Record<NodeColor, string> = {
  navy:   'bg-[#1C2340] text-white border-[#1C2340]',
  blue:   'bg-blue-50 text-blue-700 border-blue-300',
  amber:  'bg-amber-50 text-amber-700 border-amber-300',
  green:  'bg-green-50 text-green-700 border-green-300',
  purple: 'bg-purple-50 text-purple-700 border-purple-300',
}

export function Node({ color, label, sub, wide }: {
  color: NodeColor; label: string; sub?: string; wide?: boolean
}) {
  return (
    <div className={`border rounded-lg text-center px-3 py-1.5 ${wide ? 'min-w-[110px]' : 'min-w-[80px]'} ${NODE_STYLE[color]}`}>
      <div className="text-xs font-semibold">{label}</div>
      {sub && <div className="font-mono text-[10px] opacity-80 mt-0.5">{sub}</div>}
    </div>
  )
}

export function VLine() { return <div className="w-px h-3 bg-gray-300 mx-auto" /> }

// ─── Branch helper ────────────────────────────────────────────────────────────
// Renders n equal-width columns with a horizontal bridge connecting their tops.
function BranchRow({ n, children, more }: { n: number; children: React.ReactNode; more?: number }) {
  const w = n >= 3 ? n * 120 : n * 150
  return (
    <div className="relative" style={{ width: `${w}px` }}>
      {n > 1 && (
        <div
          className="absolute top-0 h-px bg-gray-300"
          style={{ left: `${50 / n}%`, right: `${50 / n}%` }}
        />
      )}
      <div className="flex">
        {children}
      </div>
      {more != null && more > 0 && (
        <div className="text-center text-[10px] text-gray-400 italic mt-1.5">+{more} more</div>
      )}
    </div>
  )
}

// ─── IMSI diagram ─────────────────────────────────────────────────────────────
export function ImsiDiagram({ data }: { data?: DiagramData }) {
  const raw = data?.imsis ?? []
  const hasReal = data != null && raw.length > 0
  const slots = hasReal
    ? raw.slice(0, 2).map((im, i) => ({
        label: `IMSI-${i + 1}`,
        sub:   im.imsi,
        ip:    im.apn_ips?.[0]?.static_ip ?? 'Auto',
      }))
    : [
        { label: 'IMSI-1', sub: '278…001', ip: '100.65.0.1' },
        { label: 'IMSI-2', sub: '278…002', ip: '100.65.0.2' },
      ]
  const n    = slots.length
  const more = hasReal && raw.length > 2 ? raw.length - 2 : 0

  return (
    <div className="flex flex-col items-center py-2 select-none">
      <Node color="navy" label="SIM Card" />
      <VLine />
      {n === 1 ? (
        <div className="flex flex-col items-center">
          <Node color="blue" label={slots[0].label} sub={slots[0].sub} />
          <VLine />
          <Node color="green" label={slots[0].ip} />
        </div>
      ) : (
        <BranchRow n={n} more={more}>
          {slots.map((s, i) => (
            <div key={i} className="flex-1 flex flex-col items-center">
              <div className="w-px h-3 bg-gray-300" />
              <Node color="blue" label={s.label} sub={s.sub} />
              <VLine />
              <Node color="green" label={s.ip} />
            </div>
          ))}
        </BranchRow>
      )}
    </div>
  )
}

// ─── IMSI + APN diagram ───────────────────────────────────────────────────────
export function ImsiApnDiagram({ data }: { data?: DiagramData }) {
  const firstImsi  = data?.imsis?.[0]
  const hasReal    = data != null && firstImsi != null
  const imsiSub    = hasReal ? firstImsi!.imsi : '278…001'
  const rawApns    = firstImsi?.apn_ips ?? []
  const hasRealApn = hasReal && rawApns.length > 0

  const apns = hasRealApn
    ? rawApns.slice(0, 2).map(ap => ({
        apn: ap.apn ?? 'any APN',
        ip:  ap.static_ip ?? 'Auto',
      }))
    : [
        { apn: 'internet', ip: '100.65.0.1' },
        { apn: 'ims',      ip: '100.65.0.2' },
      ]
  const n    = apns.length
  const more = hasRealApn && rawApns.length > 2 ? rawApns.length - 2 : 0

  return (
    <div className="flex flex-col items-center py-2 select-none">
      <Node color="navy" label="SIM Card" />
      <VLine />
      <Node color="blue" label="IMSI-1" sub={imsiSub} />
      <VLine />
      {n === 1 ? (
        <div className="flex flex-col items-center">
          <Node color="amber" label={apns[0].apn} />
          <VLine />
          <Node color="green" label={apns[0].ip} />
        </div>
      ) : (
        <BranchRow n={n} more={more}>
          {apns.map((ap, i) => (
            <div key={i} className="flex-1 flex flex-col items-center">
              <div className="w-px h-3 bg-gray-300" />
              <Node color="amber" label={ap.apn} />
              <VLine />
              <Node color="green" label={ap.ip} />
            </div>
          ))}
        </BranchRow>
      )}
      {!hasReal && (
        <div className="mt-1.5 text-[10px] text-gray-400 italic">Each IMSI × APN pair = dedicated IP</div>
      )}
    </div>
  )
}

// ─── ICCID diagram ────────────────────────────────────────────────────────────
export function IccidDiagram({ data }: { data?: DiagramData }) {
  const hasReal  = data != null
  const iccidSub = hasReal && data.iccid ? trunc(data.iccid, 6, 4) : 'ICCID-level'
  const sharedIp = data?.iccidIps?.[0]?.static_ip ?? '100.65.0.1'

  const raw   = data?.imsis ?? []
  const hasRealImsis = hasReal && raw.length > 0
  const slots = hasRealImsis
    ? raw.slice(0, 3).map((im, i) => ({ label: `IMSI-${i + 1}`, sub: im.imsi }))
    : [
        { label: 'IMSI-1', sub: '278…001' },
        { label: 'IMSI-2', sub: '278…002' },
        { label: 'IMSI-3', sub: '278…003' },
      ]
  const n    = slots.length
  const more = hasRealImsis && raw.length > 3 ? raw.length - 3 : 0

  return (
    <div className="flex flex-col items-center py-2 select-none">
      <Node color="navy" label="SIM Card" sub={iccidSub} wide />
      <VLine />
      <Node color="green" label="Shared IP" sub={sharedIp} wide />
      <VLine />
      {n === 1 ? (
        <Node color="blue" label={slots[0].label} sub={slots[0].sub} />
      ) : (
        <BranchRow n={n} more={more}>
          {slots.map((s, i) => (
            <div key={i} className="flex-1 flex flex-col items-center">
              <div className="w-px h-3 bg-gray-300" />
              <Node color="blue" label={s.label} sub={s.sub} />
            </div>
          ))}
        </BranchRow>
      )}
      {!hasReal && (
        <div className="mt-1.5 text-[10px] text-gray-400 italic">All IMSIs on the card share one IP</div>
      )}
    </div>
  )
}

// ─── ICCID + APN diagram ──────────────────────────────────────────────────────
export function IccidApnDiagram({ data }: { data?: DiagramData }) {
  const hasReal  = data != null
  const iccidSub = hasReal && data.iccid ? trunc(data.iccid, 6, 4) : 'ICCID-level'
  const rawIps   = data?.iccidIps ?? []
  const hasRealIps = hasReal && rawIps.length > 0

  const apns = hasRealIps
    ? rawIps.slice(0, 2).map(ip => ({
        apn:      ip.apn ?? 'any APN',
        sharedIp: ip.static_ip ?? 'Auto',
      }))
    : [
        { apn: 'internet', sharedIp: '100.65.0.1' },
        { apn: 'ims',      sharedIp: '100.65.0.2' },
      ]
  const n    = apns.length
  const more = hasRealIps && rawIps.length > 2 ? rawIps.length - 2 : 0

  const rawImsis = data?.imsis ?? []
  const hasRealImsis = hasReal && rawImsis.length > 0
  const imsiSlots = hasRealImsis
    ? rawImsis.slice(0, 3).map((im, i) => ({ label: `IMSI-${i + 1}`, sub: im.imsi }))
    : [
        { label: 'IMSI-1', sub: '278…001' },
        { label: 'IMSI-2', sub: '278…002' },
        { label: 'IMSI-3', sub: '278…003' },
      ]
  const imsiMore = hasRealImsis && rawImsis.length > 3 ? rawImsis.length - 3 : 0

  return (
    <div className="flex flex-col items-center py-2 select-none">
      <Node color="navy" label="SIM Card" sub={iccidSub} wide />
      <VLine />
      {n === 1 ? (
        <div className="flex flex-col items-center">
          <Node color="amber" label={apns[0].apn} />
          <VLine />
          <Node color="green" label="Shared IP" sub={apns[0].sharedIp} wide />
        </div>
      ) : (
        <BranchRow n={n} more={more}>
          {apns.map((ap, i) => (
            <div key={i} className="flex-1 flex flex-col items-center">
              <div className="w-px h-3 bg-gray-300" />
              <Node color="amber" label={ap.apn} />
              <VLine />
              <Node color="green" label="Shared IP" sub={ap.sharedIp} wide />
            </div>
          ))}
        </BranchRow>
      )}
      <VLine />
      <BranchRow n={imsiSlots.length} more={imsiMore}>
        {imsiSlots.map((s, i) => (
          <div key={i} className="flex-1 flex flex-col items-center">
            <div className="w-px h-3 bg-gray-300" />
            <Node color="blue" label={s.label} sub={s.sub} />
          </div>
        ))}
      </BranchRow>
      {!hasReal && (
        <div className="mt-1.5 text-[10px] text-gray-400 italic">All IMSIs share card-level IPs per APN</div>
      )}
    </div>
  )
}

// ─── Dispatcher ───────────────────────────────────────────────────────────────
export function ProfileDiagram({ resolution, data }: { resolution: IpResolution; data?: DiagramData }) {
  switch (resolution) {
    case 'imsi':      return <ImsiDiagram data={data} />
    case 'imsi_apn':  return <ImsiApnDiagram data={data} />
    case 'iccid':     return <IccidDiagram data={data} />
    case 'iccid_apn': return <IccidApnDiagram data={data} />
  }
}
