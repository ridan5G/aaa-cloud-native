import { NavLink, Outlet } from 'react-router-dom'

const navItems = [
  { to: '/dashboard',      label: 'Dashboard' },
  { to: '/subscribers',    label: 'Subscribers' },
  { to: '/pools',          label: 'IP Pools' },
  { to: '/range-configs',  label: 'IMSI Range Configs' },
  { to: '/bulk-jobs',      label: 'Bulk Jobs' },
]

export default function Layout() {
  return (
    <div className="flex h-screen bg-gray-50 text-gray-900">
      <aside className="w-56 shrink-0 bg-gray-900 text-gray-100 flex flex-col">
        <div className="px-6 py-5 text-lg font-semibold tracking-tight border-b border-gray-700">
          AAA Platform
        </div>
        <nav className="flex-1 px-3 py-4 space-y-1">
          {navItems.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `block px-3 py-2 rounded text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-indigo-600 text-white'
                    : 'text-gray-300 hover:bg-gray-800 hover:text-white'
                }`
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="flex-1 overflow-auto p-8">
        <Outlet />
      </main>
    </div>
  )
}
