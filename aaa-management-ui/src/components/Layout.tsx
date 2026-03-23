import { useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useToasts } from '../stores/toast'

// ─── SVG Icons ───────────────────────────────────────────────────────────────
function DashboardIcon({ c = 'w-4 h-4' }: { c?: string }) {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" className={c}>
      <rect x="1" y="1" width="6" height="6" rx="1.5" />
      <rect x="9" y="1" width="6" height="6" rx="1.5" />
      <rect x="1" y="9" width="6" height="6" rx="1.5" />
      <rect x="9" y="9" width="6" height="6" rx="1.5" />
    </svg>
  )
}
function SimIcon({ c = 'w-4 h-4' }: { c?: string }) {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className={c}>
      <rect x="3" y="1" width="10" height="14" rx="2" />
      <path d="M6 1v3h4V1" fill="currentColor" stroke="none" />
      <rect x="5" y="6" width="6" height="5" rx="1" />
    </svg>
  )
}
function PoolIcon({ c = 'w-4 h-4' }: { c?: string }) {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" className={c}>
      <path d="M8 2.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zm0 1.5a4 4 0 110 8 4 4 0 010-8z" />
      <circle cx="8" cy="8" r="2" />
    </svg>
  )
}
function NetworkIcon({ c = 'w-4 h-4' }: { c?: string }) {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" className={c}>
      <circle cx="8" cy="3" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="3" cy="13" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="13" cy="13" r="1.5" fill="currentColor" stroke="none" />
      <path d="M8 4.5v3M8 7.5L3 11.5M8 7.5L13 11.5" />
    </svg>
  )
}
function RangeIcon({ c = 'w-4 h-4' }: { c?: string }) {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" className={c}>
      <rect x="1" y="2.5" width="14" height="1.5" rx="0.75" />
      <rect x="1" y="7"   width="10" height="1.5" rx="0.75" />
      <rect x="1" y="11.5" width="12" height="1.5" rx="0.75" />
    </svg>
  )
}
function LayersIcon({ c = 'w-4 h-4' }: { c?: string }) {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" className={c}>
      <path d="M8 2L1 5.5l7 3.5 7-3.5L8 2z" />
      <path d="M1 9l7 3.5L15 9" />
      <path d="M1 12.5l7 3.5 7-3.5" />
    </svg>
  )
}
function DocIcon({ c = 'w-4 h-4' }: { c?: string }) {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" className={c}>
      <rect x="3" y="1" width="10" height="14" rx="1.5" />
      <path d="M6 5h4M6 8h4M6 11h2" strokeLinecap="round" />
    </svg>
  )
}
function JobsIcon({ c = 'w-4 h-4' }: { c?: string }) {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" className={c}>
      <rect x="1" y="1.5"  width="14" height="2.5" rx="1.25" />
      <rect x="1" y="6.75" width="14" height="2.5" rx="1.25" />
      <rect x="1" y="12"   width="14" height="2.5" rx="1.25" />
    </svg>
  )
}
function ChevronDown() {
  return (
    <svg viewBox="0 0 10 6" fill="none" stroke="currentColor" strokeWidth="1.5" className="w-2.5 h-2.5">
      <path d="M1 1l4 4 4-4" />
    </svg>
  )
}
function ChevronRight() {
  return (
    <svg viewBox="0 0 6 10" fill="none" stroke="currentColor" strokeWidth="1.5" className="w-2.5 h-2.5">
      <path d="M1 1l4 4-4 4" />
    </svg>
  )
}
function BellIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" className="w-5 h-5">
      <path d="M10 2a6 6 0 00-6 6v3l-1.5 2v1h15v-1L16 11V8a6 6 0 00-6-6z" />
      <path d="M8 16a2 2 0 004 0" />
    </svg>
  )
}
function SearchIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" className="w-4 h-4 text-gray-400">
      <circle cx="9" cy="9" r="5.5" />
      <path d="M15 15l-3-3" />
    </svg>
  )
}
function HelpIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" className="w-5 h-5">
      <circle cx="10" cy="10" r="7.5" />
      <path d="M8 8a2 2 0 114 0c0 1.5-2 2-2 3" />
      <circle cx="10" cy="14.5" r="0.75" fill="currentColor" />
    </svg>
  )
}
function HamburgerIcon() {
  return (
    <svg viewBox="0 0 18 14" fill="currentColor" className="w-4 h-4">
      <rect x="0" y="0"  width="18" height="2" rx="1" />
      <rect x="0" y="6"  width="18" height="2" rx="1" />
      <rect x="0" y="12" width="18" height="2" rx="1" />
    </svg>
  )
}

// ─── Toast Container ──────────────────────────────────────────────────────────
function ToastContainer() {
  const { toasts, dismiss } = useToasts()
  if (!toasts.length) return null
  return (
    <div className="fixed bottom-4 right-4 z-50 space-y-2 pointer-events-none">
      {toasts.map(t => (
        <div
          key={t.id}
          className={`flex items-start gap-3 px-4 py-3 bg-white rounded-lg shadow-lg border-l-4 pointer-events-auto min-w-72 max-w-sm ${
            t.type === 'success' ? 'border-green-500' :
            t.type === 'error'   ? 'border-red-500'   : 'border-primary'
          }`}
        >
          <span className="text-sm shrink-0 mt-0.5 font-bold">
            {t.type === 'success' ? '✓' : t.type === 'error' ? '✕' : 'ℹ'}
          </span>
          <p className="text-sm text-gray-700 flex-1">{t.message}</p>
          <button onClick={() => dismiss(t.id)} className="shrink-0 text-gray-400 hover:text-gray-600 leading-none text-lg">×</button>
        </div>
      ))}
    </div>
  )
}

// ─── Nav config ───────────────────────────────────────────────────────────────
const TOP_NAV = [
  { to: '/dashboard',        label: 'Dashboard',       Icon: DashboardIcon },
  { to: '/devices',          label: 'SIMs',            Icon: SimIcon },
  { to: '/pools',            label: 'IP Pools',        Icon: PoolIcon },
  { to: '/routing-domains',  label: 'Routing Domains', Icon: NetworkIcon },
]
const RANGE_CHILDREN = [
  { to: '/range-configs',       label: 'IMSI Range Configs' },
  { to: '/iccid-range-configs', label: 'ICCID Range Configs' },
]
const BOTTOM_NAV = [
  { to: '/bulk-jobs',         label: 'Bulk Jobs',    Icon: JobsIcon },
  { to: '/sim-profile-types', label: 'New SIM',             Icon: LayersIcon },
  { to: '/documentation',     label: 'Documentation',Icon: DocIcon },
]

// ─── Layout ───────────────────────────────────────────────────────────────────
export default function Layout() {
  const [collapsed, setCollapsed] = useState(false)
  const [rangeOpen, setRangeOpen] = useState(false)
  const location = useLocation()
  const isRangeActive =
    location.pathname.startsWith('/range-configs') ||
    location.pathname.startsWith('/iccid-range-configs')

  function NavItem({ to, label, Icon }: { to: string; label: string; Icon: React.ComponentType<{ c?: string }> }) {
    return (
      <NavLink
        to={to}
        className={({ isActive }) =>
          `flex items-center gap-3 px-4 py-2.5 mx-2 text-sm font-medium transition-colors rounded-md ${
            isActive
              ? 'bg-primary text-white'
              : 'text-sidebar-muted hover:text-white hover:bg-sidebar-hover'
          }`
        }
      >
        <Icon c="w-4 h-4 shrink-0" />
        {!collapsed && <span className="truncate">{label}</span>}
      </NavLink>
    )
  }

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-page font-sans">
      {/* Amber top accent strip */}
      <div className="h-[3px] bg-primary shrink-0" />

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <aside
          className={`shrink-0 bg-sidebar-bg flex flex-col transition-[width] duration-200 overflow-hidden ${
            collapsed ? 'w-14' : 'w-48'
          }`}
        >
          {/* Logo / Hamburger */}
          <div className="h-14 flex items-center px-4 gap-3 border-b border-white/10 shrink-0">
            <button
              onClick={() => setCollapsed(c => !c)}
              className="text-sidebar-muted hover:text-white transition-colors shrink-0"
              aria-label="Toggle sidebar"
            >
              <HamburgerIcon />
            </button>
            {!collapsed && (
              <span className="text-white text-sm font-semibold tracking-tight whitespace-nowrap">
                AAA Platform
              </span>
            )}
          </div>

          {/* Nav */}
          <nav className="flex-1 py-3 overflow-y-auto overflow-x-hidden space-y-0.5">
            {TOP_NAV.map(item => <NavItem key={item.to} {...item} />)}

            {/* Range Configs accordion */}
            <div>
              <button
                onClick={() => setRangeOpen(o => !o)}
                className={`w-full flex items-center gap-3 px-4 py-2.5 mx-2 text-sm font-medium transition-colors rounded-md w-[calc(100%-16px)] ${
                  isRangeActive
                    ? 'text-primary bg-primary/10'
                    : 'text-sidebar-muted hover:text-white hover:bg-sidebar-hover'
                }`}
              >
                <RangeIcon c="w-4 h-4 shrink-0" />
                {!collapsed && (
                  <>
                    <span className="flex-1 text-left whitespace-nowrap">Range Configs</span>
                    {rangeOpen || isRangeActive ? <ChevronDown /> : <ChevronRight />}
                  </>
                )}
              </button>

              {!collapsed && (rangeOpen || isRangeActive) && (
                <div className="ml-10 border-l border-white/10 pl-3 space-y-0.5 py-1 mr-2">
                  {RANGE_CHILDREN.map(child => (
                    <NavLink
                      key={child.to}
                      to={child.to}
                      className={({ isActive }) =>
                        `block px-3 py-2 text-sm rounded-md transition-colors ${
                          isActive ? 'text-white font-medium bg-sidebar-hover' : 'text-sidebar-muted hover:text-white hover:bg-sidebar-hover'
                        }`
                      }
                    >
                      {child.label}
                    </NavLink>
                  ))}
                </div>
              )}
            </div>

            {BOTTOM_NAV.map(item => <NavItem key={item.to} {...item} />)}
          </nav>
        </aside>

        {/* Main: top-bar + content */}
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {/* Top bar */}
          <header className="h-14 shrink-0 bg-white border-b border-border flex items-center px-6 gap-4">
            <div className="flex-1 max-w-xs">
              <label className="relative flex items-center">
                <span className="absolute left-3 pointer-events-none"><SearchIcon /></span>
                <input
                  type="text"
                  placeholder="Search SIM or ICCID…"
                  className="w-full pl-9 pr-3 py-1.5 text-sm border border-border rounded-md bg-page focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                />
              </label>
            </div>
            <div className="flex items-center gap-2 ml-auto">
              <button className="w-8 h-8 flex items-center justify-center text-gray-400 hover:text-gray-600 rounded-full hover:bg-gray-100">
                <BellIcon />
              </button>
              <button className="w-8 h-8 flex items-center justify-center text-gray-400 hover:text-gray-600 rounded-full hover:bg-gray-100">
                <HelpIcon />
              </button>
              <div className="flex items-center gap-2 pl-3 border-l border-border cursor-pointer select-none">
                <div className="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center text-primary font-semibold text-sm shrink-0">
                  A
                </div>
                <span className="text-sm font-medium text-gray-700 hidden lg:block">Admin</span>
                <svg viewBox="0 0 10 6" fill="none" stroke="currentColor" strokeWidth="1.5" className="w-2.5 h-2.5 text-gray-400">
                  <path d="M1 1l4 4 4-4" />
                </svg>
              </div>
            </div>
          </header>

          {/* Page content */}
          <main className="flex-1 overflow-auto p-6">
            <Outlet />
          </main>
        </div>
      </div>

      <ToastContainer />
    </div>
  )
}
